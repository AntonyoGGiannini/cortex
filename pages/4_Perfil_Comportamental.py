"""Tela 4 — Perfil Comportamental: leitura agregada dos speakers para venda interna.

Camada de inferência (dim_speaker_profile + fact_speaker_observations), separada
do cadastro curado (dim_speakers). Confiança numérica com shrinkage; evidência
citável por reunião. Uso: notas de trabalho para negociar com cada stakeholder.
"""

import streamlit as st

from lib.ui import inject_css, page_header, badge, status_bar, empty_state, filter_header
from lib import db, profiling
from lib.config import ANTHROPIC_API_KEY

st.set_page_config(page_title="Perfil Comportamental · Cortex", page_icon="🧠", layout="wide")
inject_css()
page_header(
    "🧠 Perfil Comportamental",
    "Como cada stakeholder se porta nas reuniões · base para abordagem e negociação interna",
)

DIM_LABELS = {
    "driver_decisao": "Driver de decisão",
    "estilo_processamento": "Estilo",
    "postura_conflito": "Postura em conflito",
    "peso_decisao": "Peso na decisão",
    "linguagem_gatilho": "Linguagem-gatilho",
    "padrao_objecao": "Padrão de objeção",
    "abertura": "Abertura à sua área",
}
DIM_ORDER = list(DIM_LABELS.keys())
DIR_COLOR = {"positivo": "#16A34A", "negativo": "#DC2626", "neutro": "#5A6270"}


def faixa(conf: float) -> tuple[str, str]:
    """Retorna (rótulo, kind do badge) a partir da confiança numérica."""
    if conf >= 0.55:
        return "consolidado", "ok"
    if conf >= 0.40:
        return "moderado", "info"
    return "emergente", "neutral"


# ----------------------------------------------------------------- dados
try:
    profiles = db.get_speaker_profiles()
except Exception as e:  # noqa: BLE001
    st.error("Erro ao consultar o Supabase. Verifique a SUPABASE_SERVICE_KEY no .env.")
    with st.expander("Detalhes técnicos"):
        st.code(str(e))
    st.stop()

if not profiles:
    empty_state(
        "Nenhum perfil comportamental calculado ainda.",
        "Rode o processamento das transcrições para gerar os perfis.",
        icon="🧠",
    )
    st.stop()

# ----------------------------------------------------------------- filtros (sidebar)
diretorias = sorted({p.get("diretoria") for p in profiles if p.get("diretoria")})
with st.sidebar:
    n_active = 0
    filter_header(0)
    f_dir = st.selectbox("Diretoria", ["Todas"] + diretorias)
    f_busca = st.text_input("Buscar por nome", "")
    f_min = st.select_slider(
        "Confiança mínima",
        options=["emergente", "moderado", "consolidado"],
        value="emergente",
    )
    only_playbook = st.checkbox("Só com playbook pronto", value=False)

min_conf = {"emergente": 0.0, "moderado": 0.40, "consolidado": 0.55}[f_min]

rows = [
    p
    for p in profiles
    if (f_dir == "Todas" or p.get("diretoria") == f_dir)
    and (not f_busca or f_busca.lower() in (p.get("display_name") or "").lower())
    and (p.get("conf_overall") or 0) >= min_conf
    and (not only_playbook or p.get("approach_playbook"))
]

# ----------------------------------------------------------------- KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Perfis", len(profiles))
c2.metric("Consolidados", sum(1 for p in profiles if (p.get("conf_overall") or 0) >= 0.55))
c3.metric("Moderados", sum(1 for p in profiles if 0.40 <= (p.get("conf_overall") or 0) < 0.55))
c4.metric("Com playbook", sum(1 for p in profiles if p.get("approach_playbook")))
st.write("")

# ----------------------------------------------------------------- ingestão incremental
try:
    n_pend = db.count_pending_recordings()
except Exception:  # noqa: BLE001
    n_pend = 0

with st.container(border=True):
    ic = st.columns([6, 2])
    ic[0].markdown(
        f"**Ingestão** · {n_pend} reuni{'ão' if n_pend == 1 else 'ões'} aguardando análise. "
        "Novas reuniões entram como pendentes e são processadas aqui ou pela tarefa agendada."
    )
    disabled = n_pend == 0 or not ANTHROPIC_API_KEY
    if ic[1].button(
        "⚙️ Processar pendentes",
        use_container_width=True,
        type="primary",
        disabled=disabled,
    ):
        bar = st.progress(0.0, text="Processando…")

        def _prog(i, total, res):
            bar.progress(i / max(total, 1), text=f"{i}/{total} · {res['title'] or ''}")

        try:
            out = profiling.process_pending(on_progress=_prog)
            bar.empty()
            st.success(
                f"✓ {out['reunioes_processadas']} reuniões · "
                f"{out['observacoes']} observações · "
                f"{out['perfis_recalculados']} perfis recalculados."
            )
            if out.get("aguardando_identificacao"):
                st.warning(
                    f"⏸ {out['aguardando_identificacao']} reunião(ões) não processadas: "
                    "contatos ainda em revisão. Identifique-os na página Contatos e rode de novo."
                )
            st.rerun()
        except Exception as e:  # noqa: BLE001
            bar.empty()
            st.error("Falha no processamento.")
            with st.expander("Detalhes técnicos"):
                st.code(str(e))
    if not ANTHROPIC_API_KEY:
        ic[0].caption("⚠️ Configure ANTHROPIC_API_KEY no .env para habilitar o processamento.")

st.write("")

if not rows:
    empty_state("Nenhum perfil com os filtros atuais.", "Afrouxe os filtros na barra lateral.")
    st.stop()

# ----------------------------------------------------------------- lista de perfis
for p in rows:
    conf = float(p.get("conf_overall") or 0)
    label, kind = faixa(conf)
    traits = p.get("traits") or {}

    with st.container(border=True):
        head = st.columns([5, 2, 2])
        meta = " · ".join(
            x for x in [p.get("role"), p.get("diretoria"), p.get("area")] if x
        )
        head[0].markdown(
            f"<span class='row-name'>{p.get('display_name')}</span>"
            f"<br><span class='row-meta'>{meta or '—'}</span>",
            unsafe_allow_html=True,
        )
        flags_html = ""
        if "amostra_baixa" in (p.get("flags") or []):
            flags_html = " " + badge("amostra baixa", "warn")
        head[1].markdown(
            badge(f"{label} · {conf:.2f}", kind) + flags_html, unsafe_allow_html=True
        )
        head[2].markdown(
            f"<div class='row-meta' style='text-align:right'>"
            f"{p.get('n_reunioes', 0)} reuniões · {p.get('n_observacoes', 0)} obs</div>",
            unsafe_allow_html=True,
        )

        if p.get("summary"):
            st.markdown(
                f"<div style='font-size:13px;color:#0F1117;margin:8px 0 4px'>"
                f"{p['summary']}</div>",
                unsafe_allow_html=True,
            )

        if p.get("approach_playbook"):
            st.markdown(
                f"<div style='background:#EFF6FF;border-left:3px solid #0057B8;"
                f"padding:8px 12px;border-radius:6px;font-size:12.5px;margin:6px 0'>"
                f"<b>Como abordar:</b> {p['approach_playbook']}</div>",
                unsafe_allow_html=True,
            )

        # traços por dimensão
        cells = st.columns(2)
        i = 0
        for dim in DIM_ORDER:
            t = traits.get(dim)
            if not t:
                continue
            color = DIR_COLOR.get(t.get("direction"), "#5A6270")
            tconf = t.get("conf")
            sup = t.get("support")
            cells[i % 2].markdown(
                f"<div style='margin:3px 0;font-size:12.5px'>"
                f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;"
                f"background:{color};margin-right:6px'></span>"
                f"<b>{DIM_LABELS[dim]}:</b> {t.get('trait')} "
                f"<span style='color:#9BA3AF'>({tconf} · {sup}r)</span></div>",
                unsafe_allow_html=True,
            )
            i += 1

        # evidências por reunião
        with st.expander(f"Evidências ({p.get('n_observacoes', 0)})"):
            try:
                obs = db.get_observations_for_speaker(p["speaker_id"])
            except Exception:  # noqa: BLE001
                obs = []
            if not obs:
                st.caption("Sem observações registradas.")
            else:
                last_rec = None
                for o in obs:
                    if o.get("meeting_title") != last_rec:
                        last_rec = o.get("meeting_title")
                        st.markdown(
                            f"**{last_rec or 'Reunião'}** "
                            f"<span class='row-meta'>· {o.get('meeting_date') or ''}</span>",
                            unsafe_allow_html=True,
                        )
                    color = DIR_COLOR.get(o.get("direction"), "#5A6270")
                    st.markdown(
                        f"<div style='font-size:12px;margin:2px 0 2px 10px'>"
                        f"<span style='color:{color};font-weight:700'>"
                        f"{DIM_LABELS.get(o.get('dimension'), o.get('dimension'))}</span> — "
                        f"{o.get('trait_label')}"
                        f"<br><span style='color:#8A93A2'>“{o.get('evidence') or ''}” "
                        f"· conf {o.get('conf_obs')}</span></div>",
                        unsafe_allow_html=True,
                    )

status_bar(
    "Inferência automática sobre transcrições · confiança = consistência × maturidade "
    "(shrinkage). Notas de trabalho, não avaliação de pessoas. Trate como confidencial."
)
