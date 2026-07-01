"""Tela 2 — Speakers: cadastro com chave única pelo nome normalizado (form no topo)."""

import streamlit as st

from lib.auth import require_login

from lib.ui import inject_css, page_header, status_bar, badge, empty_state, filter_header
from lib.config import SPEAKER_TYPES, DIRETORIAS, AREAS
from lib.normalize import normalize_name
from lib import db, plaud_service as ps

st.set_page_config(page_title="Contatos · Cortex", page_icon="👥", layout="wide")
require_login()
inject_css()
page_header("👥 Contatos", "Participantes únicos por nome normalizado · dim_speakers")

st.session_state.setdefault("spk_name_input", "")
# limpa o campo após salvar (feito no topo, antes do widget ser instanciado)
if st.session_state.pop("_clear_spk_name", False):
    st.session_state.spk_name_input = ""


# ================================================================= DIALOG DE EDIÇÃO
@st.dialog("Editar contato", width="large")
def speaker_dialog(s: dict) -> None:
    st.markdown(f"#### 👤 {s['display_name']}")
    with st.form(f"edit_spk_{s['speaker_key']}"):
        display_name = st.text_input("Nome de exibição", value=s.get("display_name") or "")
        c1, c2 = st.columns(2)
        with c1:
            speaker_type = st.selectbox(
                "Tipo",
                SPEAKER_TYPES,
                index=SPEAKER_TYPES.index(s["speaker_type"])
                if s.get("speaker_type") in SPEAKER_TYPES
                else 0,
            )
            company = st.text_input("Empresa", value=s.get("company") or "")
            dir_opts = [""] + DIRETORIAS
            dir_cur = s.get("diretoria") or ""
            if dir_cur and dir_cur not in dir_opts:
                dir_opts.append(dir_cur)
            diretoria = st.selectbox("Diretoria", dir_opts, index=dir_opts.index(dir_cur))
            email = st.text_input("Email", value=s.get("email") or "")
        with c2:
            role = st.text_input("Cargo", value=s.get("role") or "")
            area_opts = [""] + AREAS
            area_cur = s.get("area") or ""
            if area_cur and area_cur not in area_opts:
                area_opts.append(area_cur)
            area = st.selectbox("Área", area_opts, index=area_opts.index(area_cur))
            raw_name = st.text_input("Nome original (Plaud)", value=s.get("raw_name") or "")
        notes = st.text_area("Notas", value=s.get("notes") or "", height=80)
        save = st.form_submit_button("💾 Salvar", use_container_width=True)

    if save:
        if not display_name.strip():
            st.error("Informe o nome de exibição.")
        else:
            payload = {
                "speaker_key": s["speaker_key"],  # identidade estável (não muda)
                "display_name": display_name.strip(),
                "raw_name": raw_name.strip() or None,
                "speaker_type": speaker_type,
                "company": company.strip() or None,
                "diretoria": diretoria.strip() or None,
                "area": area.strip() or None,
                "email": email.strip() or None,
                "role": role.strip() or None,
                "notes": notes.strip() or None,
                "needs_review": False,  # editar = curado
            }
            try:
                db.upsert_speaker(payload)
                st.cache_data.clear()  # invalida o cache do dashboard
                st.toast(f"✓ Contato atualizado: {display_name.strip()}", icon="✅")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error("Erro ao salvar no Supabase.")
                with st.expander("Detalhes técnicos"):
                    st.code(str(e))


# ----------------------------------------------------------------- cadastrados
try:
    speakers = db.get_speakers()
    existing_keys = {s["speaker_key"] for s in speakers}
except Exception as e:  # noqa: BLE001
    st.error("Erro ao consultar o Supabase. Verifique a SUPABASE_SERVICE_KEY no .env.")
    with st.expander("Detalhes técnicos"):
        st.code(str(e))
    st.stop()

# ================================================================= FORM (TOPO)
with st.container(border=True):
    has_text = st.session_state.spk_name_input.strip() != ""
    fc = st.columns([6, 1])
    fc[0].markdown("#### ➕ Novo contato")
    if has_text and fc[1].button("✕ Limpar", use_container_width=True, key="clear_top"):
        st.session_state.spk_name_input = ""
        st.rerun()

    nome_preview = st.text_input("Nome de exibição", key="spk_name_input")
    key_preview = normalize_name(nome_preview)
    if nome_preview:
        if key_preview in existing_keys:
            st.warning(f"Chave `{key_preview}` já existe → o registro será **atualizado**.")
        else:
            st.caption(f"Chave gerada: `{key_preview}` (novo)")

    existing_row = db.get_speaker_by_key(key_preview) if key_preview else None

    with st.form("spk_form"):
        c1, c2 = st.columns(2)
        with c1:
            speaker_type = st.selectbox(
                "Tipo",
                SPEAKER_TYPES,
                index=SPEAKER_TYPES.index(existing_row["speaker_type"])
                if existing_row and existing_row.get("speaker_type") in SPEAKER_TYPES
                else 0,
            )
            company = st.text_input("Empresa", value=(existing_row or {}).get("company") or "")
            dir_opts = [""] + DIRETORIAS
            dir_cur = (existing_row or {}).get("diretoria") or ""
            if dir_cur and dir_cur not in dir_opts:
                dir_opts.append(dir_cur)
            diretoria = st.selectbox("Diretoria", dir_opts, index=dir_opts.index(dir_cur))
            email = st.text_input("Email", value=(existing_row or {}).get("email") or "")
        with c2:
            role = st.text_input("Cargo", value=(existing_row or {}).get("role") or "")
            area_opts = [""] + AREAS
            area_cur = (existing_row or {}).get("area") or ""
            if area_cur and area_cur not in area_opts:
                area_opts.append(area_cur)
            area = st.selectbox("Área", area_opts, index=area_opts.index(area_cur))
            raw_name = st.text_input(
                "Nome original (Plaud)", value=(existing_row or {}).get("raw_name") or ""
            )
        notes = st.text_area("Notas", value=(existing_row or {}).get("notes") or "", height=80)
        saved = st.form_submit_button("💾 Salvar / Atualizar", use_container_width=True)

    if saved:
        if not nome_preview.strip():
            st.error("Informe o nome de exibição.")
            st.stop()
        payload = {
            "speaker_key": key_preview,
            "display_name": nome_preview.strip(),
            "raw_name": raw_name.strip() or None,
            "speaker_type": speaker_type,
            "company": company.strip() or None,
            "diretoria": diretoria.strip() or None,
            "area": area.strip() or None,
            "email": email.strip() or None,
            "role": role.strip() or None,
            "notes": notes.strip() or None,
            "needs_review": False,  # salvar pelo form = curado
        }
        try:
            db.upsert_speaker(payload)
            st.cache_data.clear()  # invalida o cache do dashboard
            st.toast(f"✓ Contato salvo: {nome_preview.strip()}", icon="✅")
            st.session_state["_clear_spk_name"] = True
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error("Erro ao salvar no Supabase.")
            with st.expander("Detalhes técnicos"):
                st.code(str(e))

# ----------------------------------------------------- candidatos do Plaud (opcional)
with st.expander("🔎 Importar candidatos de uma reunião do Plaud"):
    recs = st.session_state.get("recordings")
    if not recs:
        st.caption("Abra a tela **Reuniões** e busque as reuniões primeiro.")
    else:
        opt = {f"{r.get('name') or r['id']}": r["id"] for r in recs}
        pick = st.selectbox("Reunião", list(opt.keys()), key="spk_pick_rec")
        if st.button("Listar contatos da reunião"):
            try:
                with st.spinner("Lendo contatos no Plaud..."):
                    fd = ps.get_form_data(opt[pick])
                rows = []
                for s in fd.get("speakers", []):
                    nome = s.get("name") or s.get("original_label")
                    key = normalize_name(nome)
                    rows.append({
                        "Nome": nome, "Chave": key,
                        "Status": "✓ existe" if key in existing_keys else "🟠 novo",
                        "Segmentos": s.get("segments"),
                    })
                st.session_state.spk_candidates = rows
            except Exception as e:  # noqa: BLE001
                st.error("Erro ao ler contatos no Plaud.")
                st.code(str(e))

        for i, row in enumerate(st.session_state.get("spk_candidates", [])):
            cols = st.columns([3, 2, 2, 2])
            cols[0].write(f"**{row['Nome']}**")
            cols[1].write(row["Status"])
            cols[2].write(f"{row['Segmentos']} seg.")
            if row["Status"].endswith("novo"):
                cols[3].button(
                    "Usar no form",
                    key=f"use_{i}_{row['Chave']}",
                    on_click=lambda n=row["Nome"]: st.session_state.update(spk_name_input=n),
                )

st.divider()

# ----------------------------------------------------------------- lista interativa
n_review = sum(1 for s in speakers if s.get("needs_review"))

with st.sidebar:
    n_active = sum([
        bool(st.session_state.get("spk_busca")),
        st.session_state.get("spk_tipo", "Todos") != "Todos",
        bool(st.session_state.get("spk_rev")),
    ])
    filter_header(n_active)
    s_busca = st.text_input("Buscar (nome/empresa/email)", key="spk_busca")
    s_tipo = st.selectbox("Tipo", ["Todos"] + SPEAKER_TYPES, key="spk_tipo")
    s_rev = st.checkbox(f"🔴 Só a revisar ({n_review})", key="spk_rev")


def _spk_match(s: dict) -> bool:
    if s_busca:
        blob = " ".join(
            str(s.get(k) or "")
            for k in ("display_name", "company", "email", "role", "diretoria", "area")
        ).lower()
        if s_busca.lower() not in blob:
            return False
    if s_tipo != "Todos" and s.get("speaker_type") != s_tipo:
        return False
    if s_rev and not s.get("needs_review"):
        return False
    return True


visiveis = [s for s in speakers if _spk_match(s)]

st.markdown(f"##### Cadastrados ({len(visiveis)} de {len(speakers)})")
if not speakers:
    empty_state("Nenhum contato cadastrado ainda", "Use o formulário “Novo contato” acima.", "👥")
elif not visiveis:
    empty_state("Nenhum contato com os filtros atuais", "Ajuste os filtros na barra lateral.", "🔍")
else:
    COLS = [1.6, 5.0, 1.2]
    head = st.columns(COLS)
    for c, lbl in zip(head, ["Tipo", "Contato", "Ação"]):
        c.markdown(f"<span class='col-head'>{lbl}</span>", unsafe_allow_html=True)

    for s in visiveis:
        with st.container(border=True):
            if s.get("needs_review"):
                st.markdown("<span class='mk-action'></span>", unsafe_allow_html=True)
            row = st.columns(COLS, vertical_alignment="center")
            tipo = badge(s["speaker_type"], "info")
            if s.get("needs_review"):
                tipo += " " + badge("revisar", "new")
            row[0].markdown(tipo, unsafe_allow_html=True)

            campos = [
                s.get("diretoria"), s.get("area"),
                s.get("company"), s.get("role"), s.get("email"),
            ]
            meta = " · ".join(p for p in campos if p) or "—"
            row[1].markdown(
                f"<span class='row-name'>{s['display_name']}</span><br>"
                + f"<span class='row-meta'>{meta}</span>",
                unsafe_allow_html=True,
            )
            if row[2].button("Editar", key=f"editspk_{s['speaker_key']}", use_container_width=True):
                speaker_dialog(s)

status_bar(f"{len(speakers)} contatos em dim_speakers")
         