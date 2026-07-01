"""Gate de senha simples para deploy remoto (Streamlit Community Cloud).

Uso: chame `require_login()` logo após `st.set_page_config(...)` em app.py
e em cada página de `pages/`. Se `APP_PASSWORD` não estiver configurado
(rodando local), o gate é transparente e não bloqueia nada.
"""

from __future__ import annotations

import hmac

import streamlit as st

from lib.config import APP_PASSWORD


def require_login() -> None:
    """Bloqueia a página até a senha correta ser informada.

    Guarda o estado em `st.session_state`, compartilhado entre as páginas do
    app multipage — o usuário loga uma vez por sessão.
    """
    if not APP_PASSWORD:
        return  # sem senha => uso local, não bloqueia

    if st.session_state.get("_authenticated"):
        return

    st.markdown("### 🔒 Cortex")
    st.caption("Acesso restrito. Informe a senha para continuar.")
    with st.form("login_form"):
        pwd = st.text_input("Senha", type="password")
        ok = st.form_submit_button("Entrar")

    if ok:
        if hmac.compare_digest(pwd, APP_PASSWORD):
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")

    st.stop()
