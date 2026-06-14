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

PLAUD_API = "https://api.plaud.ai"

# data_types conhecidos do content_list, em ordem de preferência para o "resumo".
# O output do template (ex.: "meeting") costuma vir como "summary"; o outline de
# tópicos vem como "outline"; a transcrição como "transaction".
TRANSCRIPT_TYPES = ("transaction", "transcript", "trans")
OUTLINE_TYPES = ("outline",)
SUMMARY_TYPES = ("summary", "ai_summary", "ai_content", "template", "mindmap")


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
        self.token = token or os.environ.get("PLAUD_TOKEN", "")
        self.timeout = timeout

    # --- HTTP base ---
    def _headers(self) -> dict:
        return {"Authorization": self.token, "Content-Type": "application/json"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{PLAUD_API}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(url, headers=self._headers(), params=params or {})
            r.raise_for_status()
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
        if start_ts:
            created = datetime.datetime.utcfromtimestamp(
                _to_seconds(start_ts)
            ).strftime("%Y-%m-%d %H:%M")
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