"""Cliente direto da API Plaud.ai, reutilizável pelo servidor MCP e pelo pipeline.

Centraliza autenticação, paginação e parsing de transcrição/outline/summary, de
forma tolerante aos diferentes formatos que a API retorna. O pipeline programado
usa este cliente diretamente (não passa pela camada MCP).
"""

import os
import json
import gzip
import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

PLAUD_API = "https://api.plaud.ai"

# data_types conhecidos do content_list, em ordem de preferência para o "resumo".
# O output do template (ex.: "meeting") costuma vir como "summary"; o outline de
# tópicos vem como "outline"; a transcrição como "transaction".
TRANSCRIPT_TYPES = ("transaction", "transcript", "trans")
OUTLINE_TYPES = ("outline",)
SUMMARY_TYPES = ("summary", "ai_summary", "ai_content", "template", "mindmap")

def _normalize_token(token: str | None) -> str:
    token = (token or "").strip()
    if not token:
        return ""
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"

def _to_seconds(ts) -> float | None:
    """Normaliza timestamps que podem vir em ms ou s."""
    if not ts:
        return None
    ts = float(ts)
    return ts / 1000 if ts > 1e10 else ts


def _fmt_clock(ms_or_s) -> str:
    """Formata um start_time (ms) como [mm:ss]."""
    if ms_or_s in (None, ""):
        return ""
    secs = int(float(ms_or_s)) // 1000
    return f"[{secs // 60:02d}:{secs % 60:02d}] "


class PlaudClient:
    def __init__(self, token: str | None = None, timeout: int = 30):
        self.token = _normalize_token(token or os.environ.get("PLAUD_TOKEN"))
        self.timeout = timeout

    # --- HTTP base ---
    def _headers(self) -> dict:
        if not self.token:
            raise RuntimeError(
                "PLAUD_TOKEN nao configurado. Crie um arquivo .env com "
                "PLAUD_TOKEN=Bearer SEU_TOKEN_AQUI"
            )
        return {"Authorization": self.token, "Content-Type": "application/json"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{PLAUD_API}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(url, headers=self._headers(), params=params or {})
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    raise RuntimeError(
                        "Plaud retornou 401 Unauthorized. O PLAUD_TOKEN esta "
                        "ausente, expirado ou invalido."
                    ) from exc
                raise
            return r.json()

    # --- Listagem ---
    def list_recordings_page(self, page: int = 1, page_size: int = 50) -> list[dict]:
        data = self._get("/file/simple/web", {"page": page, "page_size": page_size})
        if isinstance(data, dict):
            files = data.get("data") or data.get("data_file_list") or []
            if isinstance(files, dict):
                files = files.get("list") or files.get("files") or []
        else:
            files = data if isinstance(data, list) else []
        return files or []

    def iter_recordings(self, page_size: int = 100, max_pages: int = 100):
        """Itera por todas as gravações, página a página."""
        for page in range(1, max_pages + 1):
            files = self.list_recordings_page(page=page, page_size=page_size)
            if not files:
                return
            for f in files:
                yield f
            if len(files) < page_size:
                return

    @staticmethod
    def summarize_listing(f: dict) -> dict:
        """Resumo enxuto de um item de listagem (sem transcrição)."""
        duration_ms = f.get("duration") or 0
        start_ts = f.get("start_time")
        created = None
        ts = _to_seconds(start_ts)
        if ts is not None:
            created = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            )
        return {
            "id": f.get("id") or f.get("file_id"),
            "name": f.get("filename") or f.get("file_name") or f.get("name") or "sem nome",
            "duration_min": round(duration_ms / 60000, 1),
            "created_at": created,
            "has_transcript": bool(f.get("is_trans") or f.get("has_transcription")),
            "has_summary": bool(f.get("is_summary") or f.get("has_summary")),
        }

    # --- Detalhe ---
    def get_detail(self, file_id: str) -> dict:
        """Detalhe COMPLETO da gravação, incluindo content_list."""
        data = self._get(f"/file/detail/{file_id}")
        file_data = data.get("data") if isinstance(data, dict) else None
        if not isinstance(file_data, dict):
            file_data = data if isinstance(data, dict) else {}
        return file_data

    @staticmethod
    def content_types(file_data: dict) -> list[dict]:
        """Enumera os data_types disponíveis no content_list (para diagnóstico)."""
        return [
            {"data_type": item.get("data_type"), "task_status": item.get("task_status")}
            for item in file_data.get("content_list", [])
        ]

    def _find_content(self, file_data: dict, data_types) -> dict | None:
        for dt in data_types:
            for item in file_data.get("content_list", []):
                if item.get("data_type") == dt and item.get("task_status") == 1:
                    return item
        return None

    def _fetch_link(self, data_link: str):
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(data_link)
            r.raise_for_status()
            content = r.content
        if data_link.endswith(".gz") or content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        return json.loads(content)

    def _load(self, file_data: dict, data_types):
        item = self._find_content(file_data, data_types)
        if not item or not item.get("data_link"):
            return None
        return self._fetch_link(item["data_link"])

    # --- Conteúdos ---
    def get_transcript_segments(self, file_data: dict) -> list[dict]:
        trans = self._load(file_data, TRANSCRIPT_TYPES)
        if isinstance(trans, list):
            return trans
        if isinstance(trans, dict):
            return trans.get("segments") or trans.get("words") or []
        return []

    @staticmethod
    def segments_to_text(segments: list[dict]) -> str:
        lines = []
        for seg in segments:
            speaker = seg.get("speaker") or seg.get("spk") or "?"
            text = (seg.get("content") or seg.get("text") or "").strip()
            start = seg.get("start_time") or seg.get("start") or ""
            lines.append(f"{_fmt_clock(start)}{speaker}: {text}")
        return "\n".join(lines)

    def get_transcript_text(self, file_data: dict) -> str:
        return self.segments_to_text(self.get_transcript_segments(file_data))

    def get_outline(self, file_data: dict):
        """Outline de tópicos com timestamps (data_type 'outline')."""
        return self._load(file_data, OUTLINE_TYPES)

    def get_summary(self, file_data: dict):
        """Output do template (ex.: Meeting Note). Cai no outline se não houver."""
        summary = self._load(file_data, SUMMARY_TYPES)
        if summary is not None:
            return summary
        return self.get_outline(file_data)

    def get_speakers(self, file_id: str) -> list[dict]:
        """Retorna os speakers únicos da gravação com estatísticas básicas.

        Cada segmento pode ter dois campos de speaker:
          - original_speaker: label genérico original ("Speaker 1")
          - speaker: nome real identificado ("Antonyo Giannini"), quando disponível

        Retorna por speaker:
          - original_label: label original ("Speaker 1")
          - name: nome identificado, ou None se não foi identificado
          - identified: True se o nome real foi atribuído
          - segments: quantidade de segmentos
          - first_at: timestamp mm:ss da primeira fala
          - talk_time: tempo total de fala em mm:ss
          - talk_seconds: tempo total de fala em segundos (inteiro)
          - talk_words: total de palavras faladas pelo speaker
        """
        file_data = self.get_detail(file_id)
        segments = self.get_transcript_segments(file_data)

        # Chave de agrupamento: a IDENTIDADE REAL (nome) quando houver; só caímos
        # no rótulo genérico (original_speaker) para quem não foi identificado.
        # (Bug histórico: agrupar por original_speaker espalhava a mesma pessoa
        # por vários "Speaker N", e o backfill, ao indexar por nome, perdia todos
        # os pedaços menos um — subcontando drasticamente a fala.)
        speakers: dict[str, dict] = {}
        for seg in segments:
            original = (seg.get("original_speaker") or "").strip()
            identified_name = (seg.get("speaker") or seg.get("spk") or "").strip()
            key = identified_name or original or "?"

            start  = seg.get("start_time") or seg.get("start") or 0
            end    = seg.get("end_time")   or seg.get("end")   or 0
            dur_ms = seg.get("duration") or 0

            # Os timestamps do Plaud são relativos e vêm em MILISSEGUNDOS
            # (ex.: 25 min = 1.500.000 ms). Mantemos tudo em ms aqui e só
            # convertemos para segundos no final. (Bug histórico: o fallback
            # multiplicava (end-start) por 1000, inflando ~1000x.)
            if dur_ms:
                seg_ms = float(dur_ms)
            elif end:  # start pode ser 0 (1º segmento) — não usar 'and start'
                seg_ms = max(0.0, float(end) - float(start))
            else:
                seg_ms = 0.0

            # palavras faladas no segmento (métrica robusta a erro de timestamp)
            text = (seg.get("content") or seg.get("text") or seg.get("note") or "")
            seg_words = len(str(text).split())

            if key not in speakers:
                speakers[key] = {
                    "original_label": original or key,
                    "name": identified_name or None,
                    "segments": 0,
                    "first_at": _fmt_clock(start).strip(),
                    "_total_ms": 0.0,
                    "_words": 0,
                }
            # atualiza name se ainda não estava preenchido
            if speakers[key]["name"] is None and identified_name:
                speakers[key]["name"] = identified_name
            speakers[key]["segments"] += 1
            speakers[key]["_total_ms"] += seg_ms
            speakers[key]["_words"] += seg_words

        result = []
        for spk in speakers.values():
            total_s = int(spk.pop("_total_ms") / 1000)
            words = spk.pop("_words")
            talk_time = f"{total_s // 60:02d}:{total_s % 60:02d}" if total_s else "00:00"
            result.append({
                **spk,
                "identified": spk["name"] is not None,
                "talk_time": talk_time,
                "talk_seconds": total_s,
                "talk_words": words,
            })

        result.sort(key=lambda x: x["segments"], reverse=True)
        return result

    @staticmethod
    def template_header(file_data: dict) -> dict:
        """Metadados do template usado e cabeçalho de IA (categoria, headline...)."""
        extra = file_data.get("extra_data") or {}
        return {
            "used_template": extra.get("used_template") or {},
            "ai_content_header": extra.get("aiContentHeader") or {},
            "language": (extra.get("tranConfig") or {}).get("language"),
            "diarization": (extra.get("tranConfig") or {}).get("diarization"),
        }
