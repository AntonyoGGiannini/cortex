"""Core da v2 — feedback de participação do dono da base (você).

Lê o transcript de uma reunião e pede ao modelo (Anthropic) um feedback
acionável sobre como VOCÊ participou: o que fez bem, o que melhorar e um
score de influência — sempre com trecho-evidência citável da própria
transcrição. Grava em fact_participation_feedback.

Complementa a v1 (adequação de fala, determinística): a v1 diz se você falou
na medida do contexto; a v2 diz se o que você falou teve peso e como melhorar.

Usado pelo CLI (backfill_feedback.py) e pela tela de Calibragem.
Princípio: comportamento observável na reunião, nunca julgamento de caráter;
todo ponto precisa de evidência do transcript.
"""

from __future__ import annotations

from typing import Callable

from lib import db
from lib.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    ME_SPEAKER_KEY,
    PERFIL_MAX_TRANSCRIPT_CHARS,
)

# Tool que força a saída estruturada do modelo.
_TOOL = {
    "name": "registrar_feedback",
    "description": (
        "Registra um feedback de participação para a pessoa-alvo numa reunião: "
        "pontos fortes, pontos a melhorar (cada um com trecho-evidência citável) "
        "e um score de influência."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "influence_score": {
                "type": "integer",
                "description": (
                    "0-100: quanto a participação da pessoa MOVEU a reunião "
                    "(decisões conduzidas, ideias trazidas, perguntas que destravaram, "
                    "ownership). ~50 = contribuição mediana; alto = protagonista que "
                    "agrega; baixo = passivo/ausente. Densidade importa, não volume de fala."
                ),
            },
            "one_line": {
                "type": "string",
                "description": "Síntese em uma frase do papel da pessoa nesta reunião.",
            },
            "signals": {
                "type": "object",
                "properties": {
                    "n_perguntas": {"type": "integer", "description": "Perguntas que abriram/conduziram a discussão."},
                    "n_decisoes": {"type": "integer", "description": "Decisões que a pessoa conduziu ou fechou."},
                    "n_action_items": {"type": "integer", "description": "Tarefas que a pessoa assumiu para si."},
                    "n_ideias": {"type": "integer", "description": "Ideias/propostas novas trazidas pela pessoa."},
                },
                "required": ["n_perguntas", "n_decisoes", "n_action_items", "n_ideias"],
            },
            "did_well": {
                "type": "array",
                "description": "0-3 pontos fortes, cada um com evidência. Vazio se não houver.",
                "items": {
                    "type": "object",
                    "properties": {
                        "point": {"type": "string", "description": "O que fez bem, curto e específico."},
                        "evidence": {"type": "string", "description": "Trecho ou paráfrase curta do transcript que sustenta."},
                    },
                    "required": ["point", "evidence"],
                },
            },
            "to_improve": {
                "type": "array",
                "description": "0-3 pontos a melhorar, cada um com evidência e tom de coaching.",
                "items": {
                    "type": "object",
                    "properties": {
                        "point": {"type": "string", "description": "O que melhorar + como, curto e acionável."},
                        "evidence": {"type": "string", "description": "Trecho ou momento do transcript que ilustra."},
                    },
                    "required": ["point", "evidence"],
                },
            },
        },
        "required": ["influence_score", "one_line", "signals", "did_well", "to_improve"],
    },
}

_SYSTEM = (
    "Você é um coach de comunicação executiva. A partir da transcrição de uma reunião, "
    "avalia como UMA pessoa-alvo participou, para ajudá-la a melhorar. Regras: "
    "(1) avalie apenas o que é observável NESTA reunião — fala, perguntas, decisões, "
    "ownership; nunca caráter, vida pessoal, saúde ou política; "
    "(2) todo ponto (forte ou a melhorar) exige evidência do próprio transcript — cite "
    "o trecho ou descreva o momento exato; sem evidência, não registre o ponto; "
    "(3) seja específico e acionável, não genérico ('faça mais perguntas abertas' > 'comunique melhor'); "
    "(4) considere a QUALIDADE da contribuição, não o volume de fala — o quanto de fala já é medido à parte; "
    "(5) seja honesto: se a pessoa foi passiva ou dominou demais, diga, com a evidência; "
    "(6) escreva em português do Brasil, direto e executivo."
)


def _build_user_prompt(target: str, title: str, category: str, ctx: dict, transcript: str) -> str:
    t = (transcript or "")[:PERFIL_MAX_TRANSCRIPT_CHARS]
    contexto = (
        f"Pessoa-alvo (avalie só ela, nome exato no transcript): {target}\n"
        f"Reunião: {title} | Tipo: {category} | Participantes: {ctx.get('n_speakers')}\n"
        f"Dado quantitativo já medido (não recalcule): a pessoa falou "
        f"{ctx.get('share_pct')}% das palavras = {ctx.get('cota')}× a cota justa do contexto.\n\n"
    )
    return (
        contexto
        + "Gere o feedback de participação da pessoa-alvo, sempre com evidência do transcript.\n\n"
        + f"Transcrição:\n{t}"
    )


def _get_anthropic_client():
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY não configurada. Adicione no .env para rodar a extração."
        )
    import anthropic  # import tardio: só quando realmente vai extrair

    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def extract_feedback(target: str, title: str, category: str, ctx: dict, transcript: str) -> dict:
    """Chama o modelo e devolve o dict bruto do tool-use (ou {} se falhar)."""
    client = _get_anthropic_client()
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "registrar_feedback"},
        messages=[{"role": "user", "content": _build_user_prompt(target, title, category, ctx, transcript)}],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "registrar_feedback":
            return block.input if isinstance(block.input, dict) else {}
    return {}


def _clean_points(items, limit: int = 3) -> list[dict]:
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        point = (it.get("point") or "").strip()
        ev = (it.get("evidence") or "").strip()
        if not point or not ev:          # ponto sem evidência é descartado
            continue
        out.append({"point": point[:300], "evidence": ev[:500]})
        if len(out) >= limit:
            break
    return out


def _validate(raw: dict) -> dict:
    try:
        infl = int(raw.get("influence_score"))
    except (TypeError, ValueError):
        infl = None
    if infl is not None:
        infl = max(0, min(100, infl))

    sig_in = raw.get("signals") or {}
    signals = {}
    for k in ("n_perguntas", "n_decisoes", "n_action_items", "n_ideias"):
        try:
            signals[k] = max(0, int(sig_in.get(k, 0)))
        except (TypeError, ValueError):
            signals[k] = 0

    return {
        "influence_score": infl,
        "one_line": (raw.get("one_line") or "").strip()[:400] or None,
        "signals": signals,
        "did_well": _clean_points(raw.get("did_well")),
        "to_improve": _clean_points(raw.get("to_improve")),
    }


def process_recording(rec: dict, target_id: str, target_name: str, dry_run: bool = False) -> dict:
    """Extrai, valida e grava o feedback de uma reunião para a pessoa-alvo."""
    ctx = db.get_talk_context(rec["id"], target_id)
    raw = extract_feedback(
        target_name,
        rec.get("title") or "Reunião",
        rec.get("category") or "(sem tipo)",
        ctx,
        rec.get("transcript") or "",
    )
    fb = _validate(raw)
    row = {
        "recording_id": rec["id"],
        "speaker_id": target_id,
        "model": f"{ANTHROPIC_MODEL} (auto)",
        **fb,
    }
    if not dry_run:
        db.upsert_feedback(row)
    return {
        "recording_id": rec["id"],
        "title": rec.get("title"),
        "influence_score": fb["influence_score"],
        "n_fortes": len(fb["did_well"]),
        "n_melhorar": len(fb["to_improve"]),
    }


def process_pending(
    speaker_key: str = ME_SPEAKER_KEY,
    limit: int | None = None,
    dry_run: bool = False,
    on_progress: Callable[[int, int, dict], None] | None = None,
) -> dict:
    """Processa as reuniões da pessoa-alvo ainda sem feedback (com transcript)."""
    target = db.get_speaker_by_key(speaker_key)
    if not target:
        raise RuntimeError(f"Speaker '{speaker_key}' não encontrado em dim_speakers.")
    target_id, target_name = target["id"], target["display_name"]

    pend = db.get_feedback_pending(target_id, limit=limit)
    total = len(pend)
    resultados = []
    for i, rec in enumerate(pend, 1):
        res = process_recording(rec, target_id, target_name, dry_run=dry_run)
        resultados.append(res)
        if on_progress:
            on_progress(i, total, res)

    return {
        "alvo": target_name,
        "reunioes_processadas": total,
        "dry_run": dry_run,
        "detalhe": resultados,
    }
