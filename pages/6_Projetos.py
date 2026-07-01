"""Tela 6 — Projetos / Temas: o contexto completo de um tema.

Você cadastra um tema; o pipeline (lib/projects.py) varre as transcrições e junta
tudo que foi falado sobre ele em QUALQUER reunião — resumo vivo, timeline de
menções, decisões e to-dos. Governança: a IA só vincula a temas cadastrados e
toda menção carrega trecho-evidência citável.
"""

import streamlit as st

from lib.auth import require_login

from lib.ui import inject_css, page_header, badge, status_bar, empty_state
from lib import db, projects
from lib.config import ANTHROPIC_API_KEY, PROJECT_STATUS, PROJ_HYBRID_FILTER
from lib.normalize import normalize_name

st.set_page_config(page_title="Projetos / Temas · Cortex", page_icon="🗂️", layout="wide")
require_login()
inject_css()
page_header(
    "🗂️ Projetos / Temas",
    "Contexto completo de um tema, juntando tudo que foi falado em qualquer reunião",
)

STATUS_KIND = {"ativo": "ok", "pausado": "new", "concluido": "info", "arquivado": "neutral"}


def _parse_aliases(texto: str) -> list[str]:
    """Aceita aliases separados por vírgula ou quebra de linha."""
    if not texto:
        return []
    bruto = texto.replace("\n", ",").split(",")
    return [a.strip() for a in bruto if a.strip()]


def _project_form(existing: dict | None = None) -> None:
    """Formulário de cadastro/edição. existing=None -> novo tema."""
    is_edit = existing is not None
    key_prefix = f"edit_{existing['id']}" if is_edit else "novo"
    with st.form(f"form_{key_prefix}"):
        c1, c2 = st.columns([3, 1])
        name = c1.text_input("Nome do tema *", value=(existing or {}).get("name", ""))
        status = c2.selectbox(
            "Status",
            PROJECT_STATUS,
            index=PROJECT_STATUS.index((existing or {}).get("status", "ativo")),
        )
        description = st.text_area(
            "Descrição (ajuda a IA a reconhecer o tema)",
            value=(existing or {}).get("description", "") or "",
            height=70,
        )
        aliases = st.text_area(
            "Aliases — outros nomes/termos como aparecem nas calls (vírgula ou linha)",
            value=", ".join((existing or {}).get("aliases", []) or []),
            height=60,
            help="Bons aliases melhoram a captura no histórico (filtro híbrido).",
        )
        c3, c4, c5 = st.columns(3)
        area = c3.text_input("Área", value=(existing or {}).get("area", "") or "")
        owner = c4.text_input("Responsável", value=(existing or {}).get("owner", "") or "")
        jira_key = c5.text_input("Jira key (V2)", value=(existing or {}).get("jira_key", "") or "")

        salvar = st.form_submit_button(
            "💾 Salvar alterações" if is_edit else "➕ Cadastrar tema", type="primary"
        )
        if salvar:
            if not name.strip():
                st.error("O nome do tema é obrigatório.")
                return
            payload = {
                "project_key": normalize_name(name),
                "name": name.strip(),
                "description": description.strip() or None,
                "aliases": _parse_aliases(aliases),
                "status": status,
                "area": area.strip() or None,
                "owner": owner.strip() or None,
                "jira_key": jira_key.strip() or None,
            }
            try:
                if is_edit:
                    db.update_project(existing["id"], payload)
                    st.session_state.pop("proj_edit", None)
                    st.success("Tema atualizado.")
                else:
                    saved = db.upsert_project(payload)
                    st.session_state["proj_sel"] = saved.get("id")
                    st.success("Tema cadastrado. Use 'Processar este tema' para varrer o histórico.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error("Falha ao salvar. O nome pode já existir.")
                with st.expander("Detalhes técnicos"):
                    st.code(str(e))


def _export_markdown(project: dict, mentions: list[dict]) -> str:
    linhas = [f"# {project.get('name')}", ""]
    if project.get("status"):
        linhas.append(f"**Status:** {project['status']}")
    meta = " · ".join(x for x in [project.get("area"), project.get("owner")] if x)
    if meta:
        linhas.append(f"**{meta}**")
    linhas.append("")
    if project.get("consolidated_summary"):
        linhas += ["## Resumo", project["consolidated_summary"], ""]
    abertos = project.get("open_todos") or []
    if abertos:
        linhas.append("## To-dos em aberto")
        for t in abertos:
            resp = f" — _{t['responsavel']}_" if t.get("responsavel") else ""
            linhas.append(f"- {t.get('descricao')}{resp}")
        linhas.append("")
    if mentions:
        linhas.append("## Timeline de menções")
        for m in mentions:
            linhas.append(
                f"\n### {m.get('meeting_date') or '?'} · {m.get('meeting_title') or 'Reunião'}"
            )
            if m.get("update_text"):
                linhas.append(m["update_text"])
            for d in m.get("decisions") or []:
                linhas.append(f"- **Decisão:** {d}")
            for t in m.get("todos") or []:
                resp = f" ({t['responsavel']})" if t.get("responsavel") else ""
                linhas.append(f"- **To-do:** {t.get('descricao')}{resp}")
    return "\n".join(linhas)


def _run_process(project: dict) -> None:
    bar = st.progress(0.0, text="Processando…")

    def _prog(i, total, res):
        bar.progress(i / max(total, 1), text=f"{i}/{total} · {res.get('title') or ''}")

    try:
        out = projects.process_project(project, on_progress=_prog)
        bar.empty()
        st.success(
            f"✓ {out['reunioes_vistas']} reuniões vistas · "
            f"{out['chamadas_llm']} lidas pela IA · "
            f"{out['filtradas']} filtradas · {out['mencoes_novas']} menções novas."
        )
        st.rerun()
    except Exception as e:  # noqa: BLE001
        bar.empty()
        st.error("Falha no processamento.")
        with st.expander("Detalhes técnicos"):
            st.code(str(e))


# ----------------------------------------------------------------- dados
try:
    all_projects = db.get_projects()
except Exception as e:  # noqa: BLE001
    st.error("Erro ao consultar o Supabase. Verifique a SUPABASE_SERVICE_KEY no .env.")
    with st.expander("Detalhes técnicos"):
        st.code(str(e))
    st.stop()

# ----------------------------------------------------------------- KPIs
ativos = [p for p in all_projects if p.get("status") == "ativo"]
c1, c2, c3 = st.columns(3)
c1.metric("Temas", len(all_projects))
c2.metric("Ativos", len(ativos))
c3.metric("Modo backfill", "Híbrido" if PROJ_HYBRID_FILTER else "IA em todas")
st.write("")

# ----------------------------------------------------------------- ingestão global (forward)
with st.container(border=True):
    ic = st.columns([6, 2])
    ic[0].markdown(
        "**Ingestão** · processa as reuniões ainda não avaliadas para **todos os temas "
        "ativos**. Use após entrarem calls novas (ou agende via `backfill_projetos.py`)."
    )
    disabled = not ANTHROPIC_API_KEY or not ativos
    if ic[1].button("⚙️ Processar temas ativos", use_container_width=True, type="primary", disabled=disabled):
        bar = st.progress(0.0, text="Processando temas…")
        prog_state = {"i": 0}

        def _pp(nome, res):
            prog_state["i"] += 1
            bar.progress(prog_state["i"] / max(len(ativos), 1), text=f"{nome}")

        try:
            out = projects.process_all_active(on_progress=_pp)
            bar.empty()
            st.success(
                f"✓ {out['temas']} temas · {out['chamadas_llm']} leituras de IA · "
                f"{out['mencoes_novas']} menções novas."
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

# ----------------------------------------------------------------- novo tema
with st.expander("➕ Novo tema", expanded=not all_projects):
    _project_form()

# ----------------------------------------------------------------- detalhe ou lista
sel_id = st.session_state.get("proj_sel")
sel = next((p for p in all_projects if p["id"] == sel_id), None)

if sel is None:
    # ------- lista de temas -------
    if not all_projects:
        empty_state("Nenhum tema cadastrado.", "Cadastre o primeiro tema acima.", icon="🗂️")
        st.stop()
    st.markdown("##### Temas")
    for p in all_projects:
        with st.container(border=True):
            cols = st.columns([5, 2, 2, 2])
            meta = " · ".join(x for x in [p.get("area"), p.get("owner")] if x)
            cols[0].markdown(
                f"<span class='row-name'>{p.get('name')}</span>"
                f"<br><span class='row-meta'>{meta or '—'}</span>",
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                badge(p.get("status", "ativo"), STATUS_KIND.get(p.get("status"), "neutral")),
                unsafe_allow_html=True,
            )
            try:
                n_men = db.count_project_mentions(p["id"])
            except Exception:  # noqa: BLE001
                n_men = 0
            cols[2].markdown(
                f"<div class='row-meta' style='text-align:center'>{n_men} menç{'ão' if n_men == 1 else 'ões'}</div>",
                unsafe_allow_html=True,
            )
            if cols[3].button("Abrir", key=f"open_{p['id']}", use_container_width=True):
                st.session_state["proj_sel"] = p["id"]
                st.rerun()
    status_bar(
        "A IA só vincula a temas cadastrados · cada menção carrega trecho-evidência citável · "
        "trate como confidencial."
    )
    st.stop()

# ------- detalhe de um tema -------
if st.button("← Voltar para a lista"):
    st.session_state.pop("proj_sel", None)
    st.session_state.pop("proj_edit", None)
    st.rerun()

try:
    mentions = db.get_project_mentions(sel["id"])
    n_pend = db.count_unscanned_recordings(sel["id"])
except Exception as e:  # noqa: BLE001
    st.error("Erro ao carregar o tema.")
    with st.expander("Detalhes técnicos"):
        st.code(str(e))
    st.stop()

head = st.columns([5, 2])
head[0].markdown(f"### {sel.get('name')}")
head[0].markdown(
    badge(sel.get("status", "ativo"), STATUS_KIND.get(sel.get("status"), "neutral"))
    + (f" &nbsp; <span class='row-meta'>{sel.get('description')}</span>" if sel.get("description") else ""),
    unsafe_allow_html=True,
)
head[1].markdown(
    f"<div class='row-meta' style='text-align:right'>{len(mentions)} menções · "
    f"{n_pend} call{'s' if n_pend != 1 else ''} a avaliar</div>",
    unsafe_allow_html=True,
)

# ações
act = st.columns(4)
disabled_proc = not ANTHROPIC_API_KEY or n_pend == 0
if act[0].button("🔎 Processar este tema", type="primary", disabled=disabled_proc, use_container_width=True):
    _run_process(sel)
if act[1].button("♻️ Recalcular resumo", disabled=not ANTHROPIC_API_KEY or not mentions, use_container_width=True):
    try:
        with st.spinner("Recalculando resumo…"):
            projects.recompute_summary(sel["id"])
        st.success("Resumo atualizado.")
        st.rerun()
    except Exception as e:  # noqa: BLE001
        st.error("Falha ao recalcular.")
        with st.expander("Detalhes técnicos"):
            st.code(str(e))
act[2].download_button(
    "⬇️ Exportar (.md)",
    data=_export_markdown(sel, mentions),
    file_name=f"{sel.get('project_key', 'tema')}.md",
    mime="text/markdown",
    use_container_width=True,
)
if act[3].button("✏️ Editar", use_container_width=True):
    st.session_state["proj_edit"] = sel["id"]

if st.session_state.get("proj_edit") == sel["id"]:
    with st.container(border=True):
        st.markdown("**Editar tema**")
        _project_form(sel)
        if st.button("🗑️ Excluir tema", key="del"):
            db.delete_project(sel["id"])
            st.session_state.pop("proj_sel", None)
            st.session_state.pop("proj_edit", None)
            st.rerun()

if not ANTHROPIC_API_KEY:
    st.caption("⚠️ Configure ANTHROPIC_API_KEY no .env para processar e resumir.")

st.write("")

# resumo vivo
if sel.get("consolidated_summary"):
    st.markdown(
        f"<div style='background:#EFF6FF;border-left:3px solid #0057B8;padding:12px 16px;"
        f"border-radius:8px;font-size:13.5px;line-height:1.5'>"
        f"<b>Resumo vivo</b><br>{sel['consolidated_summary']}</div>",
        unsafe_allow_html=True,
    )
    if sel.get("summary_updated_at"):
        st.caption(f"Atualizado em {str(sel['summary_updated_at'])[:16].replace('T', ' ')}")
else:
    st.info("Resumo ainda não gerado. Processe o tema para montar o histórico.")

st.write("")

tab_tl, tab_dt = st.tabs([f"📌 Timeline ({len(mentions)})", "✅ Decisões & To-dos"])

# ---- timeline ----
with tab_tl:
    if not mentions:
        empty_state("Sem menções ainda.", "Processe o tema para varrer as reuniões.", icon="📌")
    else:
        spk = {}
        try:
            spk = db.get_speakers_map()
        except Exception:  # noqa: BLE001
            spk = {}
        for m in mentions:
            with st.container(border=True):
                rel = m.get("relevance")
                rel_txt = f" · relevância {rel:.0%}" if isinstance(rel, (int, float)) else ""
                st.markdown(
                    f"<span class='row-name'>{m.get('meeting_title') or 'Reunião'}</span> "
                    f"<span class='row-meta'>· {m.get('meeting_date') or ''}{rel_txt}</span>",
                    unsafe_allow_html=True,
                )
                if m.get("update_text"):
                    st.markdown(
                        f"<div style='font-size:13px;margin:4px 0'>{m['update_text']}</div>",
                        unsafe_allow_html=True,
                    )
                quem = [spk[s]["display_name"] for s in (m.get("speaker_ids") or []) if s in spk]
                if quem:
                    st.caption("👥 " + ", ".join(quem))
                excs = m.get("excerpts") or []
                if excs:
                    with st.expander(f"Trechos-evidência ({len(excs)})"):
                        for e in excs:
                            st.markdown(
                                f"<div style='font-size:12px;color:#5A6270;margin:2px 0'>“{e}”</div>",
                                unsafe_allow_html=True,
                            )

# ---- decisões & to-dos ----
with tab_dt:
    abertos = sel.get("open_todos") or []
    if abertos:
        st.markdown("**To-dos em aberto** (consolidado)")
        for t in abertos:
            resp = f" — <span class='row-meta'>{t['responsavel']}</span>" if t.get("responsavel") else ""
            st.markdown(
                f"<div style='font-size:13px;margin:3px 0'>☐ {t.get('descricao')}{resp}</div>",
                unsafe_allow_html=True,
            )
        st.divider()

    decisoes = [(m, d) for m in mentions for d in (m.get("decisions") or [])]
    todos_hist = [(m, t) for m in mentions for t in (m.get("todos") or [])]

    cda, cdb = st.columns(2)
    with cda:
        st.markdown("**Decisões (histórico)**")
        if not decisoes:
            st.caption("Nenhuma decisão registrada.")
        for m, d in decisoes:
            st.markdown(
                f"<div style='font-size:12.5px;margin:3px 0'>✔ {d}"
                f"<br><span class='row-meta'>{m.get('meeting_date') or ''} · {m.get('meeting_title') or ''}</span></div>",
                unsafe_allow_html=True,
            )
    with cdb:
        st.markdown("**To-dos (histórico)**")
        if not todos_hist:
            st.caption("Nenhum to-do registrado.")
        for m, t in todos_hist:
            resp = f" ({t['responsavel']})" if t.get("responsavel") else ""
            st.markdown(
                f"<div style='font-size:12.5px;margin:3px 0'>☐ {t.get('descricao')}{resp}"
                f"<br><span class='row-meta'>{m.get('meeting_date') or ''} · {m.get('meeting_title') or ''}</span></div>",
                unsafe_allow_html=True,
            )

status_bar(
    "Menções extraídas das transcrições com evidência citável · resumo vivo gerado por IA "
    "a partir das menções · trate como confidencial."
)
