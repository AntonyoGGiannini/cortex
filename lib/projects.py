"""Core do módulo PROJETOS / TEMAS.

Objetivo: dado um tema cadastrado (dim_projects), juntar tudo que foi falado
sobre ele em QUALQUER reunião — montando o contexto completo do tema.

Espelha o padrão de lib/profiling.py:
  - lê transcrições ainda não avaliadas para o tema (ledger fact_project_scan);
  - para cada uma, pede ao modelo (Anthropic) o que a call trouxe sobre o tema
    (update, trechos-evidência citáveis, decisões, to-dos) via tool estruturada;
  - grava em fact_project_mentions e marca o par no ledger (com/sem menção);
  - regenera o resumo vivo consolidado a partir das menções (barato: usa os
    updates curtos, não as transcrições).

Dois fluxos, mesma função `process_project`:
  - FORWARD  : call nova entra como não-avaliada para todos os temas ativos.
  - BACKFILL : tema novo entra com todas as calls antigas não-avaliadas.

Filtro híbrido (PROJ_HYBRID_FILTER): antes de gastar LLM, pré-filtra calls que
contêm o nome ou um alias do tema. As que não batem são marcadas como avaliadas
sem menção (sem chamar o modelo) — corta custo no backfill do acervo.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from lib import db
from lib.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    PROJ_MAX_TRANSCRIPT_CHARS,
    PROJ_MIN_RELEVANCE,
    PROJ_HYBRID_FILTER,
)

# --------------------------------------------------------------- tools (saída estruturada)
_EXTRACT_TOOL = {
    "name": "registrar_mencao",
    "description": (
        "Registra o que UMA reunião trouxe sobre UM tema/projeto específico. "
        "Só registre se o tema foi de fato discutido; caso contrário, marque discussed=false."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "discussed": {
                "type": "boolean",
                "description": "true se o tema foi realmente discutido nesta reunião.",
            },
            "relevance": {
                "type": "number",
                "description": "0 a 1: quão central o tema foi nesta reunião (0=passageiro, 1=foi o assunto).",
            },
            "update_text": {
                "type": "string",
                "description": "1-2 frases: o que andou, mudou ou foi dito sobre o tema NESTA reunião.",
            },
            "excerpts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Trechos/paráfrases curtas da transcrição que sustentam o registro.",
            },
            "decisions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Decisões tomadas sobre o tema nesta reunião (se houver).",
            },
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "descricao": {"type": "string"},
                        "responsavel": {"type": "string", "description": "Quem ficou responsável, se citado."},
                    },
                    "required": ["descricao"],
                },
                "description": "Ações/pendências ligadas ao tema definidas nesta reunião.",
            },
        },
        "required": ["discussed"],
    },
}

_SUMMARY_TOOL = {
    "name": "consolidar_tema",
    "description": (
        "Consolida o estado atual de um tema a partir do histórico de menções por "
        "reunião, em ordem cronológica. Sintetiza, não repete tudo."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "Resumo executivo do estado atual do tema: do que se trata, onde "
                    "está, decisões relevantes e direção. Prosa curta, sem repetir cada call."
                ),
            },
            "open_todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "descricao": {"type": "string"},
                        "responsavel": {"type": "string"},
                    },
                    "required": ["descricao"],
                },
                "description": "To-dos que continuam EM ABERTO (exclua os já resolvidos em calls posteriores).",
            },
        },
        "required": ["summary", "open_todos"],
    },
}

_EXTRACT_SYSTEM = (
    "Você é um analista de inteligência comercial. Recebe a transcrição de uma reunião "
    "e a definição de UM tema/projeto. Extraia apenas o que a reunião trouxe sobre ESSE "
    "tema. Regras: (1) só registre se o tema foi realmente discutido — menção de passagem "
    "irrelevante é discussed=false; (2) todo registro deve se apoiar na própria transcrição "
    "(use trechos como evidência); (3) não invente decisões nem to-dos que não foram ditos; "
    "(4) seja conservador na relevance — sinal fraco recebe valor baixo; (5) escreva em "
    "português, de forma objetiva e executiva."
)

_SUMMARY_SYSTEM = (
    "Você é um analista de inteligência comercial. Consolide o estado atual de um tema a "
    "partir do histórico de menções por reunião (cronológico). Sintetize a evolução, "
    "destaque decisões e direção atual, e liste só as pendências ainda em aberto. Seja "
    "objetivo e executivo, em português. Não invente nada além do que está nas menções."
)


# --------------------------------------------------------------- cliente Anthropic
def _get_anthropic_client():
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY não configurada. Adicione no .env para rodar a extração."
        )
    import anthropic  # import tardio

    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _project_block(project: dict) -> str:
    aliases = ", ".join(project.get("aliases") or []) or "—"
    return (
        f"Tema: {project.get('name')}\n"
        f"Descrição: {project.get('description') or '—'}\n"
        f"Outros nomes/termos (aliases): {aliases}"
    )


# --------------------------------------------------------------- filtro híbrido
def _build_alias_pattern(project: dict) -> re.Pattern | None:
    """Regex case-insensitive com o nome + aliases do tema (busca barata)."""
    terms = [project.get("name") or ""] + list(project.get("aliases") or [])
    terms = [t.strip() for t in terms if t and t.strip()]
    if not terms:
        return None
    parts = [re.escape(t) for t in terms]
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


def transcript_matches(project: dict, transcript: str) -> bool:
    pat = _build_alias_pattern(project)
    if pat is None:
        return False
    return bool(pat.search(transcript or ""))


# --------------------------------------------------------------- extração (1 call × 1 tema)
def extract_mention(project: dict, title: str, transcript: str) -> dict | None:
    """Chama o modelo para UM tema numa reunião. Retorna o dict bruto ou None."""
    client = _get_anthropic_client()
    t = (transcript or "")[:PROJ_MAX_TRANSCRIPT_CHARS]
    user = (
        f"{_project_block(project)}\n\n"
        f"Reunião: {title or 'Reunião'}\n\n"
        f"Transcrição:\n{t}"
    )
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        system=_EXTRACT_SYSTEM,
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "registrar_mencao"},
        messages=[{"role": "user", "content": user}],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "registrar_mencao":
            return block.input if isinstance(block.input, dict) else None
    return None


def _clean_mention(raw: dict) -> dict | None:
    """Valida/normaliza a saída do modelo. Retorna a linha pronta ou None (sem sinal)."""
    if not isinstance(raw, dict) or not raw.get("discussed"):
        return None
    try:
        rel = float(raw.get("relevance"))
    except (TypeError, ValueError):
        rel = 0.5
    rel = max(0.0, min(1.0, rel))
    if rel < PROJ_MIN_RELEVANCE:
        return None

    update = (raw.get("update_text") or "").strip()
    excerpts = [e.strip() for e in (raw.get("excerpts") or []) if isinstance(e, str) and e.strip()]
    decisions = [d.strip() for d in (raw.get("decisions") or []) if isinstance(d, str) and d.strip()]
    todos = []
    for td in raw.get("todos") or []:
        if isinstance(td, dict) and (td.get("descricao") or "").strip():
            todos.append(
                {
                    "descricao": td["descricao"].strip(),
                    "responsavel": (td.get("responsavel") or "").strip() or None,
                }
            )
    # sem nenhum conteúdo útil -> trata como não-menção
    if not (update or excerpts or decisions or todos):
        return None
    return {
        "relevance": round(rel, 2),
        "update_text": update or None,
        "excerpts": excerpts,
        "decisions": decisions,
        "todos": todos,
    }


# --------------------------------------------------------------- resumo vivo
def synthesize_summary(project: dict, mentions: list[dict]) -> dict:
    """Gera resumo consolidado + to-dos abertos a partir das menções (cronológico)."""
    client = _get_anthropic_client()
    # ordena da mais antiga p/ mais recente para o modelo ver a evolução
    ms = sorted(mentions, key=lambda m: (m.get("meeting_date") or ""))
    linhas = []
    for m in ms:
        data = m.get("meeting_date") or "?"
        titulo = m.get("meeting_title") or "Reunião"
        upd = m.get("update_text") or ""
        dec = "; ".join(m.get("decisions") or [])
        tds = "; ".join(
            (t.get("descricao") + (f" ({t['responsavel']})" if t.get("responsavel") else ""))
            for t in (m.get("todos") or [])
            if isinstance(t, dict) and t.get("descricao")
        )
        bloco = f"[{data}] {titulo}: {upd}"
        if dec:
            bloco += f"\n   Decisões: {dec}"
        if tds:
            bloco += f"\n   To-dos: {tds}"
        linhas.append(bloco)

    user = (
        f"{_project_block(project)}\n\n"
        f"Histórico de menções (cronológico):\n" + "\n".join(linhas)
    )
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1500,
        system=_SUMMARY_SYSTEM,
        tools=[_SUMMARY_TOOL],
        tool_choice={"type": "tool", "name": "consolidar_tema"},
        messages=[{"role": "user", "content": user}],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "consolidar_tema":
            data = block.input if isinstance(block.input, dict) else {}
            summary = (data.get("summary") or "").strip()
            todos = [
                {
                    "descricao": t["descricao"].strip(),
                    "responsavel": (t.get("responsavel") or "").strip() or None,
                }
                for t in (data.get("open_todos") or [])
                if isinstance(t, dict) and (t.get("descricao") or "").strip()
            ]
            return {"summary": summary, "open_todos": todos}
    return {"summary": "", "open_todos": []}


def recompute_summary(project_id: str) -> dict:
    """Recalcula o resumo vivo de um tema a partir das menções salvas e grava."""
    project = db.get_project(project_id)
    if not project:
        return {"summary": "", "open_todos": []}
    mentions = db.get_project_mentions(project_id)
    if not mentions:
        db.update_project_summary(project_id, "", [])
        return {"summary": "", "open_todos": []}
    out = synthesize_summary(project, mentions)
    db.update_project_summary(project_id, out["summary"], out["open_todos"])
    return out


# --------------------------------------------------------------- processamento
def process_project(
    project: dict,
    hybrid: bool | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    on_progress: Callable[[int, int, dict], None] | None = None,
    regenerate_summary: bool = True,
) -> dict:
    """Avalia as reuniões ainda não vistas para este tema (forward + backfill).

    hybrid: se True (padrão de config), pré-filtra por nome/alias e só manda ao LLM
    as calls que batem; as demais são marcadas como avaliadas sem menção.
    Retorna um resumo da execução.
    """
    if hybrid is None:
        hybrid = PROJ_HYBRID_FILTER

    pend = db.get_unscanned_recordings(project["id"])
    if limit:
        pend = pend[:limit]
    total = len(pend)

    n_mencoes = 0
    n_llm = 0
    n_puladas = 0
    for i, rec in enumerate(pend, 1):
        transcript = rec.get("transcript") or ""
        bate = (not hybrid) or transcript_matches(project, transcript)

        clean = None
        status = "sem_mencao"
        if bate:
            n_llm += 1
            raw = extract_mention(project, rec.get("title"), transcript)
            clean = _clean_mention(raw) if raw else None
            if clean:
                status = "mencao"
        else:
            n_puladas += 1
            status = "filtrada"

        if not dry_run:
            if clean:
                # vínculo com pessoas emerge dos dados: participantes da reunião
                # onde o tema apareceu (proxy de "quem está envolvido no tema").
                try:
                    speaker_ids = list(db.get_speaker_ids_for_recording(rec["id"]))
                except Exception:  # noqa: BLE001
                    speaker_ids = []
                db.upsert_project_mention(
                    {
                        "project_id": project["id"],
                        "recording_id": rec["id"],
                        "model": f"{ANTHROPIC_MODEL} (auto)",
                        "speaker_ids": speaker_ids,
                        **clean,
                    }
                )
                n_mencoes += 1
            db.mark_project_scanned(project["id"], rec["id"], had_mention=bool(clean))
        elif clean:
            n_mencoes += 1

        if on_progress:
            on_progress(i, total, {"title": rec.get("title"), "status": status})

    resumo_atualizado = False
    if regenerate_summary and n_mencoes and not dry_run:
        recompute_summary(project["id"])
        resumo_atualizado = True

    return {
        "project_id": project["id"],
        "name": project.get("name"),
        "reunioes_vistas": total,
        "chamadas_llm": n_llm,
        "filtradas": n_puladas,
        "mencoes_novas": n_mencoes,
        "resumo_atualizado": resumo_atualizado,
        "dry_run": dry_run,
    }


def process_all_active(
    hybrid: bool | None = None,
    limit_per_project: int | None = None,
    dry_run: bool = False,
    on_progress: Callable[[str, dict], None] | None = None,
) -> dict:
    """Processa as pendências de TODOS os temas ativos (uso típico: calls novas)."""
    projects = db.get_projects(only_active=True)
    resultados = []
    for p in projects:
        res = process_project(p, hybrid=hybrid, limit=limit_per_project, dry_run=dry_run)
        resultados.append(res)
        if on_progress:
            on_progress(p.get("name"), res)
    return {
        "temas": len(projects),
        "mencoes_novas": sum(r["mencoes_novas"] for r in resultados),
        "chamadas_llm": sum(r["chamadas_llm"] for r in resultados),
        "detalhe": resultados,
        "dry_run": dry_run,
    }
