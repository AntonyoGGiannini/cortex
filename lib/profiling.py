"""Core de extração de perfil comportamental dos speakers.

Lê transcrições pendentes, pede ao modelo (Anthropic) observações estruturadas
por participante — sempre com trecho-evidência citável — valida contra o schema
e grava em fact_speaker_observations. Depois recalcula os perfis agregados.

Usado tanto pelo CLI (backfill_perfil.py) quanto pelo botão no Streamlit.
Princípio: comportamento observável em reunião, não julgamento de caráter;
toda observação precisa de evidência da própria transcrição.
"""

from __future__ import annotations

import json
from typing import Callable

from lib import db
from lib.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    PERFIL_MAX_TRANSCRIPT_CHARS,
    PERFIL_MIN_TALK_SECONDS,
)

# --------------------------------------------------------------- schema do método
# As 7 dimensões avaliadas. A definição vai no prompt para guiar o modelo.
DIMENSIONS: dict[str, str] = {
    "driver_decisao": "O que move a pessoa a decidir: ROI/número, risco, imagem/política, relação, inovação ou conformidade.",
    "estilo_processamento": "Como processa: dado/detalhe vs. visão/síntese; rápido vs. deliberado.",
    "postura_conflito": "Como age em divergência: confronta, evita, negocia ou delega.",
    "peso_decisao": "Papel na decisão: decisor, influenciador, gatekeeper, cético-chave ou executor.",
    "linguagem_gatilho": "Termos/argumentos a que reage bem ou mal.",
    "padrao_objecao": "Como e quando costuma travar ou objetar.",
    "abertura": "Receptividade a você/à sua área: receptivo, neutro ou resistente.",
}
ALLOWED_DIMENSIONS = set(DIMENSIONS)
ALLOWED_DIRECTIONS = {"positivo", "neutro", "negativo"}

# Tool que força a saída estruturada do modelo.
_TOOL = {
    "name": "registrar_observacoes",
    "description": (
        "Registra observações comportamentais dos participantes de uma reunião, "
        "uma por traço observado, sempre com trecho-evidência citável da transcrição."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "observacoes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker_name": {"type": "string", "description": "Nome exatamente como na lista de participantes."},
                        "dimension": {"type": "string", "enum": sorted(ALLOWED_DIMENSIONS)},
                        "trait_label": {"type": "string", "description": "Rótulo curto e acionável do traço."},
                        "evidence": {"type": "string", "description": "Trecho/paráfrase curta da transcrição que sustenta o traço."},
                        "direction": {"type": "string", "enum": sorted(ALLOWED_DIRECTIONS)},
                        "conf_obs": {"type": "number", "description": "0 a 1: quão claro o sinal foi NESTA reunião."},
                    },
                    "required": ["speaker_name", "dimension", "trait_label", "evidence", "direction", "conf_obs"],
                },
            }
        },
        "required": ["observacoes"],
    },
}

_SYSTEM = (
    "Você é um analista de inteligência comercial. A partir da transcrição de uma reunião, "
    "extrai como cada participante SE PORTA, para apoiar negociação interna. Regras: "
    "(1) avalie apenas comportamento observável na reunião, nunca caráter, vida pessoal, "
    "saúde, religião ou planos de saída; (2) toda observação exige evidência da própria "
    "transcrição; (3) não perfile quem mal fala ou só faz small talk; (4) seja conservador "
    "no conf_obs — sinal fraco recebe valor baixo; (5) use somente os nomes da lista de "
    "participantes fornecida. Foque nos participantes com fala relevante."
)


def _build_user_prompt(title: str, participants: list[str], transcript: str) -> str:
    dims = "\n".join(f"- {k}: {v}" for k, v in DIMENSIONS.items())
    plist = ", ".join(participants)
    t = transcript[:PERFIL_MAX_TRANSCRIPT_CHARS]
    return (
        f"Reunião: {title}\n\n"
        f"Participantes a avaliar (use exatamente estes nomes): {plist}\n\n"
        f"Dimensões (registre 0 ou mais observações por participante, só onde houver sinal):\n{dims}\n\n"
        f"Transcrição:\n{t}"
    )


def _get_anthropic_client():
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY não configurada. Adicione no .env para rodar a extração."
        )
    import anthropic  # import tardio: só quando realmente vai extrair

    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def extract_observations(title: str, participants: list[str], transcript: str) -> list[dict]:
    """Chama o modelo e devolve a lista de observações brutas (dicts validados)."""
    client = _get_anthropic_client()
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "registrar_observacoes"},
        messages=[{"role": "user", "content": _build_user_prompt(title, participants, transcript)}],
    )
    raw: list[dict] = []
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "registrar_observacoes":
            raw = block.input.get("observacoes", []) if isinstance(block.input, dict) else []
            break
    return raw


def _validate(raw: list[dict], name_to_id: dict[str, str]) -> list[dict]:
    """Filtra e normaliza as observações do modelo contra o schema e os participantes."""
    clean = []
    for o in raw:
        if not isinstance(o, dict):
            continue
        name = (o.get("speaker_name") or "").strip()
        dim = o.get("dimension")
        direction = o.get("direction")
        if name not in name_to_id:          # nome alucinado / fora da reunião
            continue
        if dim not in ALLOWED_DIMENSIONS:
            continue
        if direction not in ALLOWED_DIRECTIONS:
            direction = "neutro"
        try:
            conf = float(o.get("conf_obs"))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        trait = (o.get("trait_label") or "").strip()
        if not trait:
            continue
        clean.append(
            {
                "speaker_id": name_to_id[name],
                "dimension": dim,
                "trait_label": trait[:240],
                "evidence": (o.get("evidence") or "").strip()[:600] or None,
                "direction": direction,
                "conf_obs": round(conf, 2),
            }
        )
    return clean


def recording_readiness(parts: list[dict]) -> tuple[bool, list[str]]:
    """Uma reunião só é processável se todos os participantes RELEVANTES (fala >= MIN)
    estiverem identificados (não needs_review, não genéricos). Caso contrário fica
    pendente até a curadoria dos speakers. Retorna (pronta, [nomes_bloqueando])."""
    relevantes = [p for p in parts if p["talk_seconds"] >= PERFIL_MIN_TALK_SECONDS]
    bloqueando = [
        p.get("display_name") or "?"
        for p in relevantes
        if p.get("needs_review") or p.get("generico")
    ]
    return (len(bloqueando) == 0, bloqueando)


def process_recording(
    rec: dict, dry_run: bool = False, respeitar_identificacao: bool = True
) -> dict:
    """Processa uma reunião: extrai, valida, grava e marca como processada.
    Pula (deixa pendente) se os speakers relevantes ainda não foram identificados.
    Retorna {recording_id, title, status, n_obs, participantes, bloqueando}."""
    parts = db.get_participants_for_recording(rec["id"])

    pronta, bloqueando = recording_readiness(parts)
    if respeitar_identificacao and not pronta:
        # NÃO marca como processada: volta a ser pega quando os speakers forem curados.
        return {
            "recording_id": rec["id"],
            "title": rec.get("title"),
            "status": "aguardando_identificacao",
            "n_obs": 0,
            "participantes": 0,
            "bloqueando": bloqueando,
        }

    elegiveis = [
        p
        for p in parts
        if p["talk_seconds"] >= PERFIL_MIN_TALK_SECONDS
        and not p.get("needs_review")
        and not p.get("generico")
    ]
    name_to_id = {p["display_name"]: p["speaker_id"] for p in elegiveis}

    n_obs = 0
    if name_to_id:
        raw = extract_observations(rec.get("title") or "Reunião", list(name_to_id), rec["transcript"])
        clean = _validate(raw, name_to_id)
        rows = [
            {**c, "recording_id": rec["id"], "model": f"{ANTHROPIC_MODEL} (auto)"}
            for c in clean
        ]
        if not dry_run:
            n_obs = db.insert_observations(rows)
        else:
            n_obs = len(rows)

    if not dry_run:
        db.mark_recording_processed(rec["id"])

    return {
        "recording_id": rec["id"],
        "title": rec.get("title"),
        "status": "processada",
        "n_obs": n_obs,
        "participantes": len(name_to_id),
        "bloqueando": [],
    }


def process_pending(
    limit: int | None = None,
    dry_run: bool = False,
    on_progress: Callable[[int, int, dict], None] | None = None,
) -> dict:
    """Processa todas as reuniões pendentes (ou até `limit`). Recalcula os perfis
    ao final. `on_progress(i, total, resultado)` é chamado a cada reunião (UI)."""
    pend = db.get_pending_recordings(limit=limit)
    total = len(pend)
    resultados = []
    for i, rec in enumerate(pend, 1):
        res = process_recording(rec, dry_run=dry_run)
        resultados.append(res)
        if on_progress:
            on_progress(i, total, res)

    processadas = [r for r in resultados if r.get("status") == "processada"]
    aguardando = [r for r in resultados if r.get("status") == "aguardando_identificacao"]

    # só recalcula se algo foi de fato gravado
    n_perfis = 0
    if processadas and not dry_run:
        n_perfis = db.recompute_profiles()

    return {
        "reunioes_vistas": total,
        "reunioes_processadas": len(processadas),
        "aguardando_identificacao": len(aguardando),
        "observacoes": sum(r["n_obs"] for r in resultados),
        "perfis_recalculados": n_perfis,
        "dry_run": dry_run,
        "detalhe": resultados,
    }
