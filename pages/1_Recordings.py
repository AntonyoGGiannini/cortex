"""Tela 1 — Recordings: Plaud -> revisão -> fact_recordings (lista interativa)."""

import datetime as dt

import streamlit as st

from lib.ui import (
    inject_css, page_header, status_bar, fmt_duration, badge,
    empty_state, filter_header,
)
from lib.config import TIPOS_REUNIAO, RECORDING_STATUS
from lib.normalize import normalize_name
from lib import db, plaud_service as ps

st.set_page_config(page_title="Reuniões · Cortex", page_icon="🎙️", layout="wide")
inject_css()
page_header("🎙️ Reuniões", "Lista do Plaud · revise e salve em fact_recordings")

# ----------------------------------------------------------------- buscar dados
top = st.columns([1, 1, 4])
with top[0]:
    limit = st.number_input("Qtde", 5, 200, 30, step=5, help="Reuniões a buscar")
with top[1]:
    st.write("")
    buscar = st.button("🔄 Buscar na Plaud", use_container_width=True)

if buscar or "recordings" not in st.session_state:
    try:
        with st.spinner("Consultando Plaud..."):
            st.session_state.recordings = ps.list_recordings(int(limit))
    except Exception as e:  # noqa: BLE001
        st.error("Erro ao buscar reuniões no Plaud.")
        with st.expander("Detalhes técnicos"):
            st.code(str(e))
        st.stop()

recordings: list[dict] = st.session_state.get("recordings", [])
if not recordings:
    empty_state("Nenhuma reunião carregada", "Clique em “Buscar na Plaud” acima.", "🎙️")
    st.stop()

# ----------------------------------------------------------------- flag registrado
try:
    rec_meta = db.get_recording_meta()
    registered = set(rec_meta)
except Exception as e:  # noqa: BLE001
    st.error("Erro ao consultar o Supabase. Verifique a SUPABASE_SERVICE_KEY no .env.")
    with st.expander("Detalhes técnicos"):
        st.code(str(e))
    st.stop()


def disp_name(r: dict) -> str:
    """Título salvo (se já registrado e não vazio) tem prioridade sobre o nome Plaud."""
    saved = (rec_meta.get(r["id"], {}).get("title") or "").strip()
    return saved or r.get("name") or r["id"]


def disp_date(r: dict) -> str:
    """Data da reunião curada (banco) p/ registradas; senão a data do Plaud."""
    md = rec_meta.get(r["id"], {}).get("meeting_date")
    if md:
        return str(md)[:10]
    return (r.get("created_at") or "")[:10] or "—"


novas = sum(1 for r in recordings if r["id"] not in registered)
m = st.columns(3)
m[0].metric("Reuniões", len(recordings))
m[1].metric("Já registradas", len(recordings) - novas)
m[2].metric("Novas", novas)


# ================================================================= DIALOG DE EDIÇÃO
@st.dialog("Revisar / editar reunião", width="large")
def recording_dialog(selected: dict) -> None:
    file_id = selected["id"]
    with st.container():
        st.markdown(f"#### 🎙️ {disp_name(selected)}")

        try:
            with st.spinner("Carregando detalhe da reunião..."):
                fd = ps.get_form_data(file_id)
        except Exception as e:  # noqa: BLE001
            st.error("Erro ao carregar o detalhe no Plaud.")
            with st.expander("Detalhes técnicos"):
                st.code(str(e))
            return

        existing = db.get_recording(file_id)
        if existing:
            st.success("Já registrada — edições abaixo **atualizam** o registro.")

        def initial(key, plaud_key=None, default=""):
            if existing and existing.get(key) not in (None, ""):
                return existing.get(key)
            return fd.get(plaud_key or key, default)

        topics = fd.get("topics") or []
        if existing and existing.get("summary"):
            summary_seed = existing["summary"]
        elif fd.get("summary_md"):
            summary_seed = fd["summary_md"]
        elif fd.get("summary_text"):
            summary_seed = fd["summary_text"]
        elif topics:
            summary_seed = "\n".join(f"• {t}" for t in topics)
        else:
            summary_seed = ""

        # override manual: usuário pediu para puxar o resumo atual do Plaud
        if st.session_state.get(f"pull_sum_{file_id}"):
            summary_seed = fd.get("summary_md") or summary_seed

        transcript_text = fd.get("transcript") or ""
        detail_meta = fd.get("detail") or {}
        pre_download = fd.get("pre_download")

        # auto-cria em dim_speakers os speakers IDENTIFICADOS pelo Plaud
        # (ignora labels genéricos "Speaker N") e já deixa pré-selecionados.
        detected, seen = [], set()
        for s in fd.get("speakers", []):
            if not s.get("identified") or not s.get("name"):
                continue
            nome = s["name"].strip()
            key = normalize_name(nome)
            if not key or key in seen:
                continue
            seen.add(key)
            detected.append((key, nome, s.get("original_label")))

        existing_keys = db.get_speaker_keys()
        criados = 0
        for key, nome, raw in detected:
            if key not in existing_keys:
                db.upsert_speaker({
                    "speaker_key": key,
                    "display_name": nome,
                    "raw_name": raw,
                    "speaker_type": "interno",
                    "needs_review": True,
                })
                criados += 1

        genericos = [
            s.get("original_label")
            for s in fd.get("speakers", [])
            if not s.get("identified")
        ]
        if criados:
            st.caption(f"➕ {criados} contato(s) criado(s) automaticamente do Plaud.")
        if genericos:
            st.caption(
                "⚠️ Não identificados (renomeie no Plaud para vincular): "
                + ", ".join(genericos)
            )

        # tempo de fala por speaker (Plaud) -> usado p/ salvar talk_seconds
        talk_by_key = {}
        if fd.get("speakers"):
            st.markdown("**🗣️ Tempo de fala (Plaud)**")
            for s in sorted(fd["speakers"], key=lambda x: x.get("talk_seconds", 0), reverse=True):
                nome = s.get("name") or s.get("original_label")
                marca = "" if s.get("identified") else " · não identificado"
                st.caption(
                    f"• {nome} — ⏱ {s.get('talk_time', '00:00')} · "
                    f"{s.get('segments', 0)} falas{marca}"
                )
                if s.get("name"):
                    talk_by_key[normalize_name(s["name"])] = {
                        "talk_seconds": s.get("talk_seconds"),
                        "talk_words": s.get("talk_words"),
                    }

        all_speakers = db.get_speakers()
        spk_options = {s["display_name"]: s["id"] for s in all_speakers}
        preselected = {nome for _, nome, _ in detected if nome in spk_options}
        if existing:
            linked = db.get_speaker_ids_for_recording(existing["id"])
            preselected |= {n for n, sid in spk_options.items() if sid in linked}
        preselected = list(preselected)

        # transcrição do Plaud (referência, somente leitura)
        with st.expander(f"📄 Transcrição do Plaud ({len(transcript_text)} caracteres)"):
            if transcript_text:
                st.text_area(
                    "Transcrição", value=transcript_text, height=260,
                    disabled=True, label_visibility="collapsed",
                )
            else:
                st.caption("Transcrição não disponível para esta reunião.")

        if existing and fd.get("summary_md") and (existing.get("summary") or "") != fd["summary_md"]:
            if st.button(
                "🔄 Puxar resumo do Plaud",
                key=f"pull_{file_id}",
                help="Substitui o resumo abaixo pelo data_content atual do Plaud.",
            ):
                st.session_state[f"pull_sum_{file_id}"] = True
                st.rerun()

        with st.form("rec_form"):
            title = st.text_input("Título", value=initial("title"))

            ca, cb, cc = st.columns(3)
            with ca:
                md = initial("meeting_date", "meeting_date")
                if isinstance(md, str):
                    md = dt.date.fromisoformat(md[:10])
                meeting_date = st.date_input("Data da reunião", value=md or dt.date.today())
            with cb:
                category = st.selectbox(
                    "Tipo de reunião",
                    TIPOS_REUNIAO,
                    index=TIPOS_REUNIAO.index(initial("category"))
                    if initial("category") in TIPOS_REUNIAO
                    else len(TIPOS_REUNIAO) - 1,
                )
            with cc:
                cur = initial("status", default="revisado")
                status = st.selectbox(
                    "Status",
                    RECORDING_STATUS,
                    index=RECORDING_STATUS.index(cur) if cur in RECORDING_STATUS else 1,
                )

            cd, ce = st.columns(2)
            with cd:
                client_name = st.text_input("Cliente", value=initial("client_name"))
            with ce:
                st.text_input(
                    "Duração", value=fmt_duration(fd.get("duration_seconds")), disabled=True
                )

            participantes = st.multiselect(
                "Participantes (já preenchidos pelo Plaud)",
                list(spk_options.keys()),
                default=preselected,
                help="Os identificados pelo Plaud já vêm marcados. Ajuste se precisar.",
            )
            summary = st.text_area("Resumo do Plaud", value=summary_seed, height=300)
            tags_str = st.text_input(
                "Tags (separadas por vírgula)",
                value=", ".join(existing.get("tags") or []) if existing else "",
            )
            submitted = st.form_submit_button(
                "💾 Salvar / Atualizar", use_container_width=True
            )

        if submitted:
            if not title.strip():
                st.error("Informe um título.")
                return
            payload = {
                "plaud_id": file_id,
                "title": title.strip(),
                "meeting_date": meeting_date.isoformat(),
                "started_at": fd.get("started_at"),
                "duration_seconds": fd.get("duration_seconds"),
                "summary": summary.strip() or None,
                "transcript": transcript_text or None,
                "category": category,
                "client_name": client_name.strip() or None,
                "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
                "language": fd.get("language") or "pt-BR",
                "status": status,
                "reviewed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "raw_payload": fd.get("raw_payload"),
            }
            try:
                saved = db.upsert_recording(payload)
                rec_id = saved.get("id")
                if rec_id:
                    db.set_recording_speakers(
                        rec_id,
                        [
                            {
                                "speaker_id": spk_options[n],
                                "talk_seconds": (talk_by_key.get(normalize_name(n)) or {}).get("talk_seconds"),
                                "talk_words": (talk_by_key.get(normalize_name(n)) or {}).get("talk_words"),
                            }
                            for n in participantes
                        ],
                    )
                st.session_state.pop(f"pull_sum_{file_id}", None)
                st.cache_data.clear()  # invalida o cache do dashboard
                st.toast(f"✓ Reunião salva: {title.strip()}", icon="✅")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error("Erro ao salvar no Supabase.")
                with st.expander("Detalhes técnicos"):
                    st.code(str(e))


st.divider()

# ----------------------------------------------------------------- filtros (sidebar)
with st.sidebar:
    n_active = sum([
        bool(st.session_state.get("rec_busca")),
        st.session_state.get("rec_status", "Todas") != "Todas",
        bool(st.session_state.get("rec_transc")),
    ])
    filter_header(n_active)
    f_busca = st.text_input("Buscar por nome", key="rec_busca")
    f_status = st.radio(
        "Situação", ["Todas", "Novas", "Registradas"], key="rec_status"
    )
    f_transc = st.checkbox("Só com transcrição", key="rec_transc")


def _match(r: dict) -> bool:
    if f_busca and f_busca.lower() not in disp_name(r).lower():
        return False
    is_reg = r["id"] in registered
    if f_status == "Novas" and is_reg:
        return False
    if f_status == "Registradas" and not is_reg:
        return False
    if f_transc and not r.get("has_transcript"):
        return False
    return True


filtered = [r for r in recordings if _match(r)]

# ----------------------------------------------------------------- lista interativa
st.markdown(f"##### Reuniões ({len(filtered)})")
if not filtered:
    empty_state("Nenhuma reunião com os filtros atuais", "Ajuste os filtros na barra lateral.", "🔍")

COLS = [1.5, 5.0, 1.0, 1.5]
head = st.columns(COLS)
for c, lbl in zip(head, ["Status", "Reunião", "Transc.", "Ação"]):
    c.markdown(f"<span class='col-head'>{lbl}</span>", unsafe_allow_html=True)

for r in filtered:
    fid = r["id"]
    is_reg = fid in registered
    with st.container(border=True):
        if not is_reg:
            st.markdown("<span class='mk-action'></span>", unsafe_allow_html=True)
        row = st.columns(COLS, vertical_alignment="center")
        row[0].markdown(
            badge("Registrado", "ok") if is_reg else badge("Nova", "new"),
            unsafe_allow_html=True,
        )
        meta = f"🗓 {disp_date(r)} · ⏱ {r.get('duration_min', 0):.0f} min"
        row[1].markdown(
            f"<span class='row-name'>{disp_name(r)}</span><br>"
            + f"<span class='row-meta'>{meta}</span>",
            unsafe_allow_html=True,
        )
        row[2].markdown("✅" if r.get("has_transcript") else "—")
        if row[3].button(
            "Editar" if is_reg else "Revisar",
            key=f"openrec_{fid}",
            use_container_width=True,
            type="secondary" if is_reg else "primary",
        ):
            recording_dialog(r)

status_bar(
    f"{len(filtered)} de {len(recordings)} reuniões exibidas · "
    f"{len(registered)} já no banco"
)
