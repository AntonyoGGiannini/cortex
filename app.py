"""Cortex — Control Tower (Home).

Ingestão Plaud -> revisão human-in-the-loop -> Supabase.
Use o menu lateral: Recordings (reuniões) e Speakers (participantes).
"""

import streamlit as st

from lib.ui import inject_css, page_header, status_bar, status_pill
from lib.config import SUPABASE_SERVICE_KEY, PLAUD_TOKEN
from lib.auth import require_login

st.set_page_config(page_title="Cortex", page_icon="🧠", layout="wide")
require_login()
inject_css()

page_header("🧠 Cortex — Control Tower", "Plaud → revisão → Supabase (cortex_db)")

plaud_ok = bool(PLAUD_TOKEN)
db_ok = bool(SUPABASE_SERVICE_KEY)

# --- conexões (status) ---
conn = st.columns([1, 1, 2])
conn[0].markdown(
    status_pill("Plaud", plaud_ok, "conectado", "sem token"), unsafe_allow_html=True
)
conn[1].markdown(
    status_pill("Supabase", db_ok, "configurado", "sem chave"), unsafe_allow_html=True
)

st.write("")

# --- KPIs do banco ---
n_rec = n_spk = n_rev = None
if db_ok:
    try:
        from lib import db

        n_rec = db.count_recordings()
        n_spk = db.count_speakers()
        n_rev = db.count_speakers_needing_review()
        k = st.columns(3)
        k[0].metric("Reuniões", n_rec)
        k[1].metric("Contatos", n_spk)
        k[2].metric("A revisar", n_rev, delta="pendente" if n_rev else None,
                    delta_color="inverse")
        if n_rev:
            if k[2].button("Revisar pendentes →", use_container_width=True, key="goto_review"):
                st.session_state.spk_rev = True
                st.switch_page("pages/2_👥_Speakers.py")
    except Exception as e:  # noqa: BLE001
        st.error("Falha ao conectar no Supabase.")
        with st.expander("Detalhes técnicos"):
            st.code(str(e))

st.divider()

if not db_ok:
    st.warning(
        "Configure **SUPABASE_SERVICE_KEY** no arquivo `.env` "
        "(service_role key do projeto cortex_db) para habilitar a gravação."
    )
if not plaud_ok:
    st.warning("Configure **PLAUD_TOKEN** no `.env` para listar as reuniões.")

st.markdown(
    """
    **Fluxo**

    1. **Reuniões** — lista as reuniões do Plaud, marca as já registradas,
       você revisa/edita e salva em `fact_recordings`.
    2. **Contatos** — cadastra os participantes com chave única pelo nome
       normalizado em `dim_speakers`, e vincula à reunião.

    Abra as telas no menu lateral. ☰
    """
)

if n_spk is not None:
    status_bar(f"{n_rec} reuniões · {n_spk} contatos cadastrados · projeto cortex_db")
