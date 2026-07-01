"""Cortex — Dashboard analítico.

Cruza reuniões × speakers para responder: pra onde vai minha atenção,
quem domina/escuta, quem está esfriando e onde a captura falhou.

Recorte principal: por pessoa. Métrica de fala: talk_words (exato);
talk_seconds (aproximado) entra como apoio.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from lib.ui import inject_css, page_header, status_bar, empty_state, filter_header
from lib.config import SUPABASE_SERVICE_KEY, ME_SPEAKER_KEY
from lib import db

st.set_page_config(page_title="Cortex · Dashboard", page_icon="📊", layout="wide")
inject_css()
page_header("📊 Dashboard", "Reuniões × pessoas — atenção, fala/escuta, cadência e captura")

if not SUPABASE_SERVICE_KEY:
    st.warning("Configure **SUPABASE_SERVICE_KEY** no `.env` para carregar o dashboard.")
    st.stop()

HOJE = dt.date.today()
IGNORAR = {"AI Chat"}  # ruído de IA do Plaud — fora das análises


# ----------------------------------------------------------------- carga
@st.cache_data(ttl=300, show_spinner="Carregando dados…")
def carregar() -> dict:
    recs = pd.DataFrame(db.get_recordings_min())
    bridge = pd.DataFrame(db.get_bridge_all())
    spk = pd.DataFrame(db.get_speakers())
    cob = pd.DataFrame(db.get_cobertura())
    return {"recs": recs, "bridge": bridge, "spk": spk, "cob": cob,
            "loaded_at": dt.datetime.now()}


try:
    D = carregar()
except Exception as e:  # noqa: BLE001
    st.error("Erro ao carregar dados do Supabase.")
    with st.expander("Detalhes técnicos"):
        st.code(str(e))
    st.stop()

recs, bridge, spk, cob = D["recs"], D["bridge"], D["spk"], D["cob"]

if recs.empty or bridge.empty or spk.empty:
    empty_state("Sem dados suficientes para o dashboard",
                "Registre reuniões e vincule participantes nas telas Reuniões e Contatos.", "📊")
    st.stop()

# tipos
recs["meeting_date"] = pd.to_datetime(recs["meeting_date"], errors="coerce")
recs["duration_seconds"] = pd.to_numeric(recs["duration_seconds"], errors="coerce").fillna(0)
for c in ("talk_seconds", "talk_words"):
    bridge[c] = pd.to_numeric(bridge[c], errors="coerce").fillna(0)

# tabela base: um registro por (reunião, speaker)
base = (
    bridge.merge(recs, left_on="recording_id", right_on="id", suffixes=("", "_rec"))
    .merge(spk, left_on="speaker_id", right_on="id", suffixes=("", "_spk"))
)
base = base[~base["display_name"].isin(IGNORAR)].copy()
base["diretoria"] = base["diretoria"].fillna("(sem diretoria)")
base["area"] = base["area"].fillna("(sem área)")
base["category"] = base["category"].fillna("(sem tipo)")

me_ids = set(spk.loc[spk["speaker_key"] == ME_SPEAKER_KEY, "id"])


# ----------------------------------------------------------------- filtros
_all_tipos = sorted(spk["speaker_type"].dropna().unique())
_all_dirs = sorted(base["diretoria"].unique())
with st.sidebar:
    n_active = sum([
        st.session_state.get("dash_per", "Tudo") != "Tudo",
        0 < len(st.session_state.get("dash_tipo", _all_tipos)) < len(_all_tipos),
        0 < len(st.session_state.get("dash_dir", _all_dirs)) < len(_all_dirs),
    ])
    if st.button("🔄 Atualizar dados", use_container_width=True, key="dash_refresh"):
        carregar.clear()
        st.rerun()
    filter_header(n_active)
    periodo = st.radio(
        "Período", ["Últimos 30 dias", "Últimos 90 dias", "Tudo"], index=2, key="dash_per"
    )
    tipos = st.multiselect(
        "Tipo de stakeholder", _all_tipos, default=_all_tipos, key="dash_tipo",
    )
    diretorias = st.multiselect("Diretoria", _all_dirs, default=_all_dirs, key="dash_dir")

# janela temporal
if periodo == "Últimos 30 dias":
    desde = pd.Timestamp(HOJE - dt.timedelta(days=30))
elif periodo == "Últimos 90 dias":
    desde = pd.Timestamp(HOJE - dt.timedelta(days=90))
else:
    desde = recs["meeting_date"].min()

mask = (
    (base["meeting_date"] >= desde)
    & (base["speaker_type"].isin(tipos))
    & (base["diretoria"].isin(diretorias))
)
fb = base[mask].copy()                       # base filtrada (com você incluído)
fb_out = fb[~fb["speaker_id"].isin(me_ids)]  # sem você (ranking de stakeholders)
recs_per = recs[recs["meeting_date"] >= desde]

if fb.empty:
    empty_state("Nenhuma reunião no recorte atual", "Amplie o período ou limpe os filtros.", "🔍")
    status_bar("0 reuniões no recorte atual")
    st.stop()


# ----------------------------------------------------------------- KPIs
n_reunioes = fb["recording_id"].nunique()
horas_total = recs_per["duration_seconds"].sum() / 3600
n_stake = fb_out["speaker_id"].nunique()

palavras_total = fb["talk_words"].sum()
minhas_palavras = fb[fb["speaker_id"].isin(me_ids)]["talk_words"].sum()
fala_pct = (100 * minhas_palavras / palavras_total) if palavras_total else 0

cob_med = None
if not cob.empty:
    cob["meeting_date"] = pd.to_datetime(cob["meeting_date"], errors="coerce")
    cobf = cob[cob["meeting_date"] >= desde]
    if not cobf.empty:
        cob_med = cobf["cobertura_pct"].median()

k = st.columns(5)
k[0].metric("Reuniões", f"{n_reunioes}")
k[1].metric("Horas em reunião", f"{horas_total:.1f}h")
k[2].metric("Stakeholders", f"{n_stake}")
k[3].metric("Sua fala", f"{fala_pct:.0f}%", delta=f"escuta {100-fala_pct:.0f}%", delta_color="off")
k[4].metric("Cobertura média", f"{cob_med:.0f}%" if cob_med is not None else "—")

st.divider()

aba_aloc, aba_voz, aba_cad, aba_cob = st.tabs(
    ["⏱ Alocação de tempo", "🗣️ Fala / escuta", "📅 Cadência", "✅ Cobertura"]
)


# =================================================================== alocação
with aba_aloc:
    st.caption("Quanto do seu tempo de reunião é investido em cada pessoa (duração da reunião, não fala).")
    aloc = (
        fb_out.groupby(["display_name", "speaker_type", "diretoria"])
        .agg(reunioes=("recording_id", "nunique"),
             horas=("duration_seconds", lambda s: round(s.sum() / 3600, 1)),
             ultima=("meeting_date", "max"))
        .reset_index()
        .sort_values("horas", ascending=False)
    )
    aloc["ultima"] = aloc["ultima"].dt.strftime("%d/%m/%Y")
    st.dataframe(
        aloc, use_container_width=True, hide_index=True,
        column_config={
            "display_name": st.column_config.TextColumn("Pessoa"),
            "speaker_type": st.column_config.TextColumn("Tipo"),
            "diretoria": st.column_config.TextColumn("Diretoria"),
            "reunioes": st.column_config.NumberColumn("Reuniões", format="%d"),
            "horas": st.column_config.ProgressColumn(
                "Horas", format="%.1f h", min_value=0,
                max_value=float(aloc["horas"].max() or 1),
            ),
            "ultima": st.column_config.TextColumn("Última"),
        },
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Horas por diretoria**")
        por_dir = (fb_out.groupby("diretoria")["duration_seconds"]
                   .sum().div(3600).round(1).sort_values(ascending=False))
        st.bar_chart(por_dir, horizontal=True, color="#0057B8")
    with c2:
        st.markdown("**Horas por tipo de reunião**")
        por_cat = (recs_per.assign(h=recs_per["duration_seconds"] / 3600)
                   .groupby(recs_per["category"].fillna("(sem tipo)"))["h"]
                   .sum().round(1).sort_values(ascending=False))
        st.bar_chart(por_cat, horizontal=True, color="#5A6270")


# =================================================================== fala/escuta
with aba_voz:
    st.caption("Share of voice por palavras (exato). Em reunião de grupo, a fatia individual é pequena por definição.")
    cE, cR = st.columns([1, 2])
    with cE:
        st.markdown("**Você: fala × escuta**")
        donut = pd.DataFrame(
            {"parte": ["Fala", "Escuta"], "pct": [round(fala_pct, 1), round(100 - fala_pct, 1)]}
        ).set_index("parte")
        st.bar_chart(donut, color="#0057B8")
        ref = "ouvindo mais que falando ✅" if fala_pct < 50 else "falando mais que ouvindo ⚠️"
        st.caption(f"Você fala **{fala_pct:.0f}%** das palavras — {ref}")
    with cR:
        st.markdown("**Share of voice por pessoa** (% das palavras nas reuniões em que participou)")
        tot_por_reuniao = fb.groupby("recording_id")["talk_words"].sum().rename("tot")
        voz = fb_out.merge(tot_por_reuniao, on="recording_id")
        voz_g = (voz.groupby("display_name")
                 .agg(palavras=("talk_words", "sum"),
                      tot=("tot", "sum"),
                      reunioes=("recording_id", "nunique"))
                 .reset_index())
        voz_g["share_pct"] = (100 * voz_g["palavras"] / voz_g["tot"]).round(0)
        voz_g = voz_g.sort_values("palavras", ascending=False)[
            ["display_name", "reunioes", "palavras", "share_pct"]
        ]
        st.dataframe(
            voz_g, use_container_width=True, hide_index=True,
            column_config={
                "display_name": st.column_config.TextColumn("Pessoa"),
                "reunioes": st.column_config.NumberColumn("Reuniões", format="%d"),
                "palavras": st.column_config.NumberColumn("Palavras", format="%d"),
                "share_pct": st.column_config.ProgressColumn(
                    "Share médio", format="%d%%", min_value=0, max_value=100
                ),
            },
        )


# =================================================================== cadência
with aba_cad:
    st.caption("Cadência considera todo o histórico (ignora o filtro de período). Vermelho = relação esfriando.")
    base_cad = base[
        base["speaker_type"].isin(tipos) & base["diretoria"].isin(diretorias)
        & ~base["speaker_id"].isin(me_ids)
    ]
    cad = (base_cad.groupby(["display_name", "speaker_type", "diretoria"])
           .agg(reunioes=("recording_id", "nunique"), ultima=("meeting_date", "max"))
           .reset_index())
    cad["dias"] = (pd.Timestamp(HOJE) - cad["ultima"]).dt.days
    cad["semanas"] = (cad["dias"] / 7).round(0)
    cad = cad.sort_values("dias", ascending=False)

    frios = int((cad["semanas"] >= 6).sum())
    if frios:
        st.markdown(f"🔴 **{frios}** stakeholder(s) sem contato há 6+ semanas.")
    cad_show = cad.assign(ultima=cad["ultima"].dt.strftime("%d/%m/%Y"))[
        ["display_name", "speaker_type", "diretoria", "reunioes", "semanas", "ultima"]
    ]
    st.dataframe(
        cad_show, use_container_width=True, hide_index=True,
        column_config={
            "display_name": st.column_config.TextColumn("Pessoa"),
            "speaker_type": st.column_config.TextColumn("Tipo"),
            "diretoria": st.column_config.TextColumn("Diretoria"),
            "reunioes": st.column_config.NumberColumn("Reuniões", format="%d"),
            "semanas": st.column_config.NumberColumn("Semanas sem contato", format="%d"),
            "ultima": st.column_config.TextColumn("Última reunião"),
        },
    )


# =================================================================== cobertura
with aba_cob:
    st.caption("Qualidade de captura. Abaixo de ~70% = segmentos sem timing no Plaud ou curadoria pendente.")
    if cob.empty:
        st.info("View vw_cobertura_reuniao sem dados.")
    else:
        cobf = cob[cob["meeting_date"] >= desde].copy()
        baixas = int((cobf["cobertura_pct"] < 70).sum())
        if baixas:
            st.markdown(f"⚠️ **{baixas}** reunião(ões) com cobertura abaixo de 70%.")
        cobf["meeting_date"] = pd.to_datetime(cobf["meeting_date"], errors="coerce").dt.strftime("%d/%m/%Y")
        cobf = cobf.sort_values("cobertura_pct")[
            ["title", "meeting_date", "n_speakers", "palavras_total", "cobertura_pct"]
        ]
        st.dataframe(
            cobf, use_container_width=True, hide_index=True,
            column_config={
                "title": st.column_config.TextColumn("Reunião"),
                "meeting_date": st.column_config.TextColumn("Data"),
                "n_speakers": st.column_config.NumberColumn("Pessoas", format="%d"),
                "palavras_total": st.column_config.NumberColumn("Palavras", format="%d"),
                "cobertura_pct": st.column_config.ProgressColumn(
                    "Cobertura", format="%d%%", min_value=0, max_value=100
                ),
            },
        )

_fresh = D.get("loaded_at")
_fresh_txt = f"atualizado {_fresh.strftime('%H:%M')}" if _fresh else "dados em cache"
status_bar(
    f"{n_reunioes} reuniões · {n_stake} stakeholders · recorte: {periodo.lower()} · "
    f"fala/escuta por palavras (exato) · {_fresh_txt}"
)
