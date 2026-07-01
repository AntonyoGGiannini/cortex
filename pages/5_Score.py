"""Cortex — Calibragem de Participação (você).

Não entrega uma nota abstrata: entrega DECISÃO. Para cada reunião diz se você
foi bem, o motivo (quanto falou vs. a sua cota justa no contexto) e o que fazer.

Métrica base: eng = (sua fala / fala total) × nº de participantes = quantas
vezes a sua "cota justa" você ocupou. 1,0 = exatamente a cota. <1 = abaixo,
>1 = acima. As faixas-alvo variam por tipo de reunião (um 1:1 pede equilíbrio;
uma apresentação pede protagonismo). Score 0–100 só alimenta a evolução.

Foco: calibrar minha fala (onde falo demais / de menos) e acompanhar evolução.
Métrica de fala: talk_words (exato). Espelha as views v_participation_*.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from lib.auth import require_login

from lib.ui import inject_css, page_header, status_bar, empty_state, filter_header, badge
from lib.config import SUPABASE_SERVICE_KEY, ME_SPEAKER_KEY
from lib import db

st.set_page_config(page_title="Cortex · Calibragem", page_icon="🎯", layout="wide")
require_login()
inject_css()
page_header(
    "🎯 Calibragem de Participação",
    "Onde você fala demais, onde fala de menos — e o que ajustar",
)

if not SUPABASE_SERVICE_KEY:
    st.warning("Configure **SUPABASE_SERVICE_KEY** no `.env` para carregar.")
    st.stop()

HOJE = dt.date.today()
IGNORAR = {"AI Chat"}

# Faixa-alvo por tipo de reunião, em "× cota justa" (eng). Espelha o CASE da
# view v_participation_meeting. Calibrável (governança do score).
BANDAS: dict[str, tuple[float, float]] = {
    "1:1": (0.7, 1.2),
    "Alinhamento": (0.8, 1.4),
    "Weekly": (1.0, 1.8),
    "Mensal": (0.8, 1.6),
    "Apresentação": (1.2, 2.2),
    "Projeto": (0.5, 1.5),
    "Itaú": (0.5, 1.5),
}
BANDA_PADRAO = (0.8, 1.5)


def banda(categoria: str | None) -> tuple[float, float]:
    return BANDAS.get(categoria or "", BANDA_PADRAO)


def score_reuniao(eng: float, n: int, lo: float, hi: float) -> float:
    if lo > 0 and eng < lo:
        return round(100.0 * eng / lo, 1)
    if eng <= hi:
        return 100.0
    denom = n - hi
    if denom <= 0:
        return 100.0
    return round(100.0 - 50.0 * min((eng - hi) / denom, 1.0), 1)


def veredito(score: float, eng: float, hi: float) -> str:
    if score >= 85:
        return "ok"
    return "muito" if eng > hi else "pouco"


VRD = {  # (rótulo, ícone, cor)
    "ok": ("No ponto", "🟢", "#16A34A"),
    "muito": ("Falou demais", "🟡", "#D97706"),
    "pouco": ("Falou de menos", "🔴", "#DC2626"),
}


def como_melhorar(vrd: str, categoria: str) -> str:
    if vrd == "ok":
        return "Nível certo para o contexto. Mantém."
    if vrd == "muito":
        if categoria == "1:1":
            return "Num 1:1 o palco é do outro: faça perguntas abertas e segure os silêncios."
        if categoria == "Apresentação":
            return "Conduzir é esperado aqui — só evite atropelar as perguntas da plateia."
        return "Você puxou acima da cota. Abra espaço para o time fechar os pontos."
    # pouco
    if categoria == "1:1":
        return "1:1 também é seu espaço de liderar: leve pauta e direcione a conversa."
    if categoria in ("Projeto", "Itaú", "Apresentação"):
        return "Tema da sua área e fala baixa — prepare 2–3 pontos para trazer da próxima."
    return "Garanta ao menos uma contribuição objetiva na próxima."


# ----------------------------------------------------------------- carga
@st.cache_data(ttl=300, show_spinner="Calculando…")
def carregar() -> dict:
    speakers = db.get_speakers()
    recs = pd.DataFrame(db.get_recordings_min())
    bridge = pd.DataFrame(db.get_bridge_all())
    spk = pd.DataFrame(speakers)
    me = next((s for s in speakers if s["speaker_key"] == ME_SPEAKER_KEY), None)
    fb = db.get_participation_feedback(me["id"]) if me else []
    return {"recs": recs, "bridge": bridge, "spk": spk, "fb": fb,
            "loaded_at": dt.datetime.now()}


try:
    D = carregar()
except Exception as e:  # noqa: BLE001
    st.error("Erro ao carregar dados do Supabase.")
    with st.expander("Detalhes técnicos"):
        st.code(str(e))
    st.stop()

recs, bridge, spk = D["recs"], D["bridge"], D["spk"]
fb_map = {f["recording_id"]: f for f in D.get("fb", [])}
if recs.empty or bridge.empty or spk.empty:
    empty_state("Sem dados para calcular", "Registre reuniões e vincule participantes.", "🎯")
    st.stop()

recs["meeting_date"] = pd.to_datetime(recs["meeting_date"], errors="coerce")
recs["duration_seconds"] = pd.to_numeric(recs["duration_seconds"], errors="coerce").fillna(0)
bridge["talk_words"] = pd.to_numeric(bridge["talk_words"], errors="coerce")

me_ids = set(spk.loc[spk["speaker_key"] == ME_SPEAKER_KEY, "id"])
if not me_ids:
    st.error(f"Contato `{ME_SPEAKER_KEY}` não encontrado em dim_speakers.")
    st.stop()

bridge = bridge.merge(spk[["id", "display_name"]], left_on="speaker_id", right_on="id", how="left")
bridge = bridge[~bridge["display_name"].isin(IGNORAR)].copy()

tot = (
    bridge.groupby("recording_id")
    .agg(n_speakers=("speaker_id", "nunique"), tot_words=("talk_words", "sum"))
    .reset_index()
)
minhas = (
    bridge[bridge["speaker_id"].isin(me_ids)]
    .groupby("recording_id")["talk_words"].sum().rename("ant_words").reset_index()
)
m = (
    recs.rename(columns={"id": "recording_id"})
    .merge(tot, on="recording_id", how="inner")
    .merge(minhas, on="recording_id", how="left")
)
m["category"] = m["category"].fillna("(sem tipo)")

attended = set(bridge[bridge["speaker_id"].isin(me_ids)]["recording_id"])
m["participei"] = m["recording_id"].isin(attended)
m["pontuavel"] = m["tot_words"].fillna(0).gt(0) & m["ant_words"].notna()

sc = m[m["pontuavel"]].copy()
sem_dados = m[(~m["pontuavel"]) & m["participei"]].copy()
if sc.empty:
    empty_state("Nenhuma reunião pontuável ainda", "Falta talk_words por participante.", "🎯")
    st.stop()

sc["share_pct"] = (100.0 * sc["ant_words"] / sc["tot_words"]).round(1)
sc["cota"] = sc["ant_words"] / sc["tot_words"] * sc["n_speakers"]  # × cota justa (eng cheio)
_b = sc["category"].map(banda)
sc["lo"] = _b.map(lambda b: b[0])
sc["hi"] = _b.map(lambda b: b[1])
sc["score"] = sc.apply(lambda r: score_reuniao(r["cota"], r["n_speakers"], r["lo"], r["hi"]), axis=1)
sc["vrd"] = sc.apply(lambda r: veredito(r["score"], r["cota"], r["hi"]), axis=1)


# ----------------------------------------------------------------- filtros
_cats = sorted(sc["category"].unique())
with st.sidebar:
    n_active = sum([
        st.session_state.get("sc_per", "Tudo") != "Tudo",
        0 < len(st.session_state.get("sc_cat", _cats)) < len(_cats),
    ])
    if st.button("🔄 Atualizar dados", use_container_width=True, key="sc_refresh"):
        carregar.clear()
        st.rerun()
    filter_header(n_active)
    periodo = st.radio("Período", ["Últimos 30 dias", "Últimos 90 dias", "Tudo"],
                       index=2, key="sc_per")
    cats = st.multiselect("Tipo de reunião", _cats, default=_cats, key="sc_cat")

if periodo == "Últimos 30 dias":
    desde = pd.Timestamp(HOJE - dt.timedelta(days=30))
elif periodo == "Últimos 90 dias":
    desde = pd.Timestamp(HOJE - dt.timedelta(days=90))
else:
    desde = sc["meeting_date"].min()

f = sc[(sc["meeting_date"] >= desde) & (sc["category"].isin(cats))].copy()
if f.empty:
    empty_state("Nenhuma reunião no recorte", "Amplie o período ou limpe os filtros.", "🔍")
    status_bar("0 reuniões no recorte")
    st.stop()

n = len(f)
n_muito = int((f["vrd"] == "muito").sum())
n_pouco = int((f["vrd"] == "pouco").sum())
n_ok = int((f["vrd"] == "ok").sum())


# ----------------------------------------------------------------- veredito do período
if n_muito > n_pouco and n_muito / n >= 0.35:
    cat_dom = f[f["vrd"] == "muito"]["category"].mode()
    onde = f" — concentrado em **{cat_dom.iloc[0]}**" if not cat_dom.empty else ""
    leitura = (f"Seu padrão é **falar acima da cota** ({n_muito} de {n} reuniões){onde}. "
               "O ajuste é abrir mais espaço para os outros.")
elif n_pouco > n_muito and n_pouco / n >= 0.35:
    cat_aus = f[f["vrd"] == "pouco"]["category"].mode()
    onde = f" — sobretudo em **{cat_aus.iloc[0]}**" if not cat_aus.empty else ""
    leitura = (f"Seu padrão é **ficar abaixo da cota** ({n_pouco} de {n} reuniões){onde}. "
               "O ajuste é marcar mais presença.")
else:
    leitura = (f"Participação **equilibrada** na maioria ({n_ok} de {n} no ponto). "
               "Ajustes pontuais abaixo.")

st.markdown(
    f"<div style='background:#FFFFFF;border:1px solid #E5E7EB;border-left:4px solid #0057B8;"
    f"border-radius:8px;padding:14px 16px;font-size:14px;color:#0F1117'>{leitura}</div>",
    unsafe_allow_html=True,
)
st.write("")

infl_vals = [fb_map[rid]["influence_score"] for rid in f["recording_id"]
             if rid in fb_map and fb_map[rid].get("influence_score") is not None]
infl_med = round(sum(infl_vals) / len(infl_vals)) if infl_vals else None
n_fb = sum(1 for rid in f["recording_id"] if rid in fb_map)

k = st.columns(4)
k[0].metric("Falar menos", n_muito, help="Reuniões em que você falou acima da faixa do contexto.")
k[1].metric("Falar mais", n_pouco, help="Reuniões em que você ficou abaixo da faixa.")
k[2].metric("No ponto", n_ok, help="Participação adequada ao contexto.")
k[3].metric("Influência média", f"{infl_med}" if infl_med is not None else "—",
            help="v2: quanto suas falas moveram a reunião (decisões, ideias, perguntas). 0–100.")

if n_fb == 0:
    st.caption("💡 Evidência (v2) ainda não gerada. Rode `python backfill_feedback.py` "
               "(precisa de ANTHROPIC_API_KEY no .env) para ver o *porquê* e dicas por reunião.")
elif n_fb < n:
    st.caption(f"v2: evidência gerada em {n_fb} de {n} reuniões do recorte. "
               "Rode `python backfill_feedback.py` para completar.")

st.divider()
aba_calibrar, aba_evol, aba_metodo = st.tabs(
    ["🎚 O que ajustar", "📈 Evolução", "ℹ️ Como funciona"]
)


# =================================================================== o que ajustar
def cartao(r: pd.Series) -> None:
    rot, ic, cor = VRD[r["vrd"]]
    data = r["meeting_date"].strftime("%d/%m") if pd.notna(r["meeting_date"]) else "—"
    mark = "<span class='mk-action'></span>" if r["vrd"] != "ok" else ""
    with st.container(border=True):
        st.markdown(
            f"{mark}<span class='row-name'>{ic} {r['title']}</span> "
            f"{badge(r['category'], 'neutral')} "
            f"<span class='row-meta'>· {data} · {r['n_speakers']} pessoas</span>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<span style='color:{cor};font-weight:700'>{rot}</span>"
            f"<span class='row-meta'> — falou <b>{r['share_pct']:.0f}%</b> das palavras "
            f"(<b>{r['cota']:.1f}× a sua cota</b>)</span>",
            unsafe_allow_html=True,
        )
        st.markdown(f"<span class='row-meta'>➜ {como_melhorar(r['vrd'], r['category'])}</span>",
                    unsafe_allow_html=True)

        fb = fb_map.get(r["recording_id"])
        if fb:
            infl = fb.get("influence_score")
            cab = f"Por quê — evidência da reunião{f' · influência {infl}/100' if infl is not None else ''}"
            with st.expander(cab):
                if fb.get("one_line"):
                    st.markdown(f"_{fb['one_line']}_")
                for it in fb.get("did_well") or []:
                    st.markdown(f"✅ **{it['point']}**  \n<span class='row-meta'>“{it['evidence']}”</span>",
                                unsafe_allow_html=True)
                for it in fb.get("to_improve") or []:
                    st.markdown(f"🔧 **{it['point']}**  \n<span class='row-meta'>“{it['evidence']}”</span>",
                                unsafe_allow_html=True)


with aba_calibrar:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**🟡 Falar menos** · {n_muito}")
        muito = f[f["vrd"] == "muito"].sort_values("score")
        if muito.empty:
            st.caption("Nada a reduzir no recorte. 👍")
        for _, r in muito.iterrows():
            cartao(r)
    with c2:
        st.markdown(f"**🔴 Falar mais** · {n_pouco}")
        pouco = f[f["vrd"] == "pouco"].sort_values("score")
        if pouco.empty:
            st.caption("Nenhuma ausência relevante no recorte. 👍")
        for _, r in pouco.iterrows():
            cartao(r)

    with st.expander(f"🟢 No ponto ({n_ok}) — manter"):
        ok = f[f["vrd"] == "ok"].sort_values("meeting_date", ascending=False)
        for _, r in ok.iterrows():
            st.markdown(
                f"🟢 {r['title']} · {r['meeting_date'].strftime('%d/%m')} · "
                f"{r['share_pct']:.0f}% ({r['cota']:.1f}× cota)"
            )
    if not sem_dados.empty:
        st.caption(f"⚠️ {len(sem_dados)} reunião(ões) sua(s) ficaram fora (sem talk_words).")


# =================================================================== evolução
with aba_evol:
    ev = f.sort_values("meeting_date").copy()
    ev["semana"] = ev["meeting_date"].dt.to_period("W").apply(lambda p: p.start_time)

    # tendência: 1ª vs 2ª metade do recorte
    meio = len(ev) // 2
    if meio >= 2:
        s1 = ev.iloc[:meio]["score"].mean()
        s2 = ev.iloc[meio:]["score"].mean()
        d = s2 - s1
        seta = "🟢 melhorando" if d > 3 else ("🔴 piorando" if d < -3 else "⚪ estável")
        st.markdown(f"**Tendência:** {seta}  ·  adequação {s1:.0f} → {s2:.0f}")
    st.caption("Adequação semanal (0–100, ponderada por duração). 100 = sempre no ponto.")

    sem = (
        ev.assign(w=ev["duration_seconds"].clip(lower=1))
        .groupby("semana")
        .apply(lambda d: round((d["score"] * d["w"]).sum() / d["w"].sum(), 1))
    )
    sem.index = sem.index.strftime("%d/%m")
    st.line_chart(sem, color="#0057B8")

    st.caption("Sua fala vs. cota justa por semana (1,0 = cota). Acima da faixa = tende a dominar.")
    cota_sem = ev.groupby("semana")["cota"].mean().round(2)
    cota_sem.index = cota_sem.index.strftime("%d/%m")
    st.bar_chart(cota_sem, color="#5A6270")

    ev["influencia"] = ev["recording_id"].map(
        lambda rid: (fb_map.get(rid) or {}).get("influence_score"))
    if ev["influencia"].notna().any():
        st.caption("Influência por semana (v2 — quanto suas falas moveram a reunião, 0–100).")
        infl_sem = ev.dropna(subset=["influencia"]).groupby("semana")["influencia"].mean().round(0)
        infl_sem.index = infl_sem.index.strftime("%d/%m")
        st.line_chart(infl_sem, color="#16A34A")


# =================================================================== método
with aba_metodo:
    st.markdown(
        """
**A ideia em uma frase:** participar bem não é falar muito, é falar **na medida do contexto**.

- **× cota justa** = quantas vezes a sua parte proporcional você ocupou.
  1,0 = exatamente sua cota; 2,0 = falou o dobro; 0,3 = quase não falou.
  Já corrige o tamanho da reunião (50% num 1:1 e 12,5% numa de 8 dão a mesma cota).
- **Faixa-alvo por tipo:** 1:1 0,7–1,2 · Alinhamento 0,8–1,4 · Weekly 1,0–1,8 ·
  Mensal 0,8–1,6 · Apresentação 1,2–2,2 · Projeto/Itaú 0,5–1,5.
- **Veredito:** dentro da faixa = *no ponto*; acima = *falou demais*; abaixo = *falou de menos*.
- **Evolução** usa um score 0–100 (100 = sempre no ponto) só para ver a direção no tempo.

Métrica de fala: **talk_words** (exato). Reuniões sem diarização ficam fora.

**v2 — evidência (ativa):** o transcript é analisado por LLM, que aponta o *porquê*
(o que você fez bem / a melhorar, com trechos reais) e um score de **influência**
(0–100: quanto suas falas moveram a reunião). Gere/atualize com
`python backfill_feedback.py` (requer ANTHROPIC_API_KEY no .env). A v1 (adequação)
continua determinística; a v2 só acrescenta a leitura qualitativa.
        """
    )

_fresh = D.get("loaded_at")
_txt = f"atualizado {_fresh.strftime('%H:%M')}" if _fresh else "cache"
status_bar(
    f"{n} reuniões · falar menos {n_muito} / falar mais {n_pouco} / no ponto {n_ok} · "
    f"recorte: {periodo.lower()} · fala por palavras (exato) · {_txt}"
)
