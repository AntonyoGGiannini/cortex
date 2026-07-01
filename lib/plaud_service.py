"""Camada de serviço sobre o PlaudClient: prepara dados para a UI e para o banco.

A listagem (rápida) é usada na tabela. O detalhe (start_time, headline, speakers)
só é buscado quando o usuário abre uma gravação para revisar — evita N chamadas
pesadas na montagem da lista.
"""

from __future__ import annotations

import datetime as _dt
import json
from zoneinfo import ZoneInfo

import streamlit as st

from plaud_client import PlaudClient
from lib.config import LOCAL_TZ


def _extract_pre_download(pre_download):
    """Extrai o resumo em markdown e os blocos de pre_download_content_list.

    Cada item tem `data_id` (ex.: 'auto_sum:...') e `data_content` (markdown).
    Retorna (summary_md, blocos) onde blocos = [{'tipo', 'content'}].
    """
    blocos, summary_md = [], ""
    if isinstance(pre_download, list):
        for it in pre_download:
            if not isinstance(it, dict):
                continue
            did = str(it.get("data_id") or "")
            tipo = did.split(":")[0] if did else ""
            content = it.get("data_content") or ""
            blocos.append({"tipo": tipo, "content": content})
            if not summary_md and ("sum" in tipo.lower()):
                summary_md = content
        if not summary_md and blocos:
            summary_md = blocos[0]["content"]
    return summary_md, blocos


def _content_to_text(data) -> str:
    """Normaliza conteúdo do Plaud (str/list/dict) em texto legível."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        linhas = []
        for it in data:
            if isinstance(it, dict):
                t = it.get("topic") or it.get("content") or it.get("text") or it.get("note")
                if t:
                    linhas.append(f"• {t}")
            elif isinstance(it, str):
                linhas.append(f"• {it}")
        return "\n".join(linhas)
    if isinstance(data, dict):
        for k in ("summary", "content", "markdown", "md", "text"):
            if data.get(k):
                return str(data[k])
        return json.dumps(data, ensure_ascii=False, indent=2)
    return str(data)


@st.cache_resource
def get_plaud() -> PlaudClient:
    return PlaudClient()


def _epoch_ms_to_utc(ms) -> _dt.datetime | None:
    if not ms:
        return None
    secs = float(ms)
    if secs > 1e11:  # ms -> s
        secs /= 1000
    return _dt.datetime.fromtimestamp(secs, _dt.timezone.utc)


# --------------------------------------------------------------------- listagem
@st.cache_data(ttl=300, show_spinner=False)
def list_recordings(limit: int = 50) -> list[dict]:
    """Resumo enxuto das gravações (sem detalhe). Cacheado por 5 min."""
    client = get_plaud()
    files = client.list_recordings_page(page=1, page_size=limit)
    return [client.summarize_listing(f) for f in files]


# ---------------------------------------------------------------------- detalhe
@st.cache_data(ttl=600, show_spinner=False)
def get_form_data(file_id: str) -> dict:
    """Monta os campos do formulário de reunião a partir do detalhe Plaud.

    Cacheado por file_id (invalida ao mudar o código ou via cache_data.clear()).
    Retorna chaves alinhadas a fact_recordings (mais 'topics' e 'speakers'
    auxiliares para a UI).
    """
    client = get_plaud()
    file_data = client.get_detail(file_id)
    header = client.template_header(file_data)
    ai = header.get("ai_content_header") or {}

    start_dt = _epoch_ms_to_utc(file_data.get("start_time"))
    duration_ms = file_data.get("duration") or 0

    # tópicos (outline) -> ajudam o usuário a escrever o resumo
    topics: list[str] = []
    summary = client.get_summary(file_data)
    if isinstance(summary, list):
        topics = [t.get("topic") for t in summary if isinstance(t, dict) and t.get("topic")]

    # conteúdos do call buscados no Plaud
    transcript_text = client.get_transcript_text(file_data)
    summary_text = _content_to_text(summary)

    # metadados (get_recording_detail). pre_download_content_list é separado
    # (info principal). Exclui só os blobs pesados/binários do raw_payload.
    heavy = ("content_list", "embeddings", "download_path_mapping",
             "pre_download_content_list")
    detail_meta = {k: v for k, v in file_data.items() if k not in heavy}
    pre_download = file_data.get("pre_download_content_list")
    summary_md, pre_blocks = _extract_pre_download(pre_download)

    # data local (America/Sao_Paulo) para meeting_date
    meeting_date = None
    started_at_iso = None
    if start_dt:
        started_at_iso = start_dt.isoformat()
        meeting_date = start_dt.astimezone(ZoneInfo(LOCAL_TZ)).date()

    return {
        "plaud_id": str(file_id),
        "title": ai.get("headline") or file_data.get("filename") or "",
        "started_at": started_at_iso,
        "meeting_date": meeting_date,
        "duration_seconds": int(float(duration_ms) / 1000) if duration_ms else None,
        "category": ai.get("category") or "",
        "language": header.get("language") or "pt-BR",
        "topics": topics,
        "transcript": transcript_text,
        "summary_text": summary_text,
        "summary_md": summary_md,
        "detail": detail_meta,
        "pre_download": pre_download,
        "pre_blocks": pre_blocks,
        "speakers": client.get_speakers(file_id),  # [{original_label, name, identified,...}]
        "raw_payload": {**detail_meta, "pre_download_content_list": pre_download},
    }
