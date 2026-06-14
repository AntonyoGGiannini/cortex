import os
import json
import re
import requests
import threading
from dotenv import load_dotenv

load_dotenv()

# Anthropic MCP proxy (usado quando PLAUD_API_TOKEN = sk-ant-si-...)
_PROXY_URL = (
    "https://api.anthropic.com/v2/ccr-sessions/cse_01763jZd33pJiwWaUcDNxNJd/mcp"
    "?mcp_url=https%3A%2F%2Fplaud-production.up.railway.app%2Fsse"
    "&mcp_server_id=41123f61-4ab7-5aa0-91c8-c29b77fcb683"
    "&toolbox_mcp_server_id=49263282-122e-40a0-84e6-86412d28e703"
)
_SESSION_UUID = "cse_01763jZd33pJiwWaUcDNxNJd"
_MCP_SERVER_ID = "49263282-122e-40a0-84e6-86412d28e703"

# Plaud MCP server direto (usado quando PLAUD_JWT_TOKEN = eyJ...)
_PLAUD_MCP_SSE = "https://plaud-production.up.railway.app/sse"

_TOKEN_FILE_CANDIDATES = [
    os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE", ""),
    "/home/claude/.claude/remote/.session_ingress_token",
    os.path.expanduser("~/.claude/remote/.session_ingress_token"),
]


def _get_session_token() -> str | None:
    token = os.environ.get("PLAUD_API_TOKEN", "")
    if token and token.startswith("sk-ant-si-"):
        return token
    for path in _TOKEN_FILE_CANDIDATES:
        if path and os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
    return None


def _get_jwt() -> str | None:
    token = os.environ.get("PLAUD_JWT_TOKEN", "")
    return token if token.startswith("eyJ") else None


def _call_via_proxy(name: str, arguments: dict) -> str:
    """Chama via proxy Anthropic com o token de sessão Claude Code."""
    token = _get_session_token()
    if not token:
        raise RuntimeError("Token de sessão Claude Code não encontrado.")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Session-UUID": _SESSION_UUID,
        "X-MCP-Server-ID": _MCP_SERVER_ID,
        "Content-Type": "application/json",
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    resp = requests.post(_PROXY_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            data = json.loads(line[6:])
            result = data.get("result", {})
            if result.get("isError"):
                raise RuntimeError(result["content"][0]["text"])
            return result["content"][0]["text"]
    raise ValueError("Nenhum dado retornado pelo proxy")


def _call_via_mcp_sse(name: str, arguments: dict) -> str:
    """Chama o servidor MCP do Plaud diretamente com o JWT do usuário."""
    jwt = _get_jwt()
    if not jwt:
        raise RuntimeError("PLAUD_JWT_TOKEN não definido no .env")

    headers_auth = {"Authorization": f"Bearer {jwt}"}
    messages_endpoint: list[str] = []
    error: list[Exception] = []
    result_data: list[str] = []
    done = threading.Event()

    def listen_sse():
        try:
            with requests.get(
                _PLAUD_MCP_SSE, headers=headers_auth, stream=True, timeout=15
            ) as sse_resp:
                sse_resp.raise_for_status()
                event_type = ""
                for raw in sse_resp.iter_lines(decode_unicode=True):
                    if not raw:
                        event_type = ""
                        continue
                    if raw.startswith("event:"):
                        event_type = raw[6:].strip()
                    elif raw.startswith("data:"):
                        data_val = raw[5:].strip()
                        if event_type == "endpoint":
                            base = _PLAUD_MCP_SSE.rsplit("/sse", 1)[0]
                            messages_endpoint.append(base + data_val)
                            done.set()
                            return
        except Exception as e:
            error.append(e)
            done.set()

    t = threading.Thread(target=listen_sse, daemon=True)
    t.start()
    done.wait(timeout=10)

    if error:
        raise RuntimeError(f"Erro ao conectar no MCP SSE: {error[0]}")
    if not messages_endpoint:
        raise RuntimeError("Endpoint do MCP não retornado via SSE")

    endpoint = messages_endpoint[0]
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    resp = requests.post(endpoint, headers={**headers_auth, "Content-Type": "application/json"}, json=payload, timeout=30)
    resp.raise_for_status()
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            data = json.loads(line[6:])
            result = data.get("result", {})
            if result.get("isError"):
                raise RuntimeError(result["content"][0]["text"])
            return result["content"][0]["text"]
    raise ValueError("Nenhum dado retornado pelo MCP direto")


def _call_tool(name: str, arguments: dict) -> str:
    """Detecta automaticamente o modo.

    Prioridade:
    1. Arquivo de sessão Claude Code presente → proxy Anthropic (ambiente remoto)
    2. PLAUD_JWT_TOKEN definido → MCP direto (máquina local)
    3. PLAUD_API_TOKEN definido → proxy Anthropic (fallback)
    """
    for path in _TOKEN_FILE_CANDIDATES:
        if path and os.path.exists(path):
            return _call_via_proxy(name, arguments)
    if _get_jwt():
        return _call_via_mcp_sse(name, arguments)
    if _get_session_token():
        return _call_via_proxy(name, arguments)
    raise RuntimeError(
        "Nenhuma credencial encontrada.\n"
        "Adicione ao arquivo .env:\n"
        "  PLAUD_JWT_TOKEN=eyJ...   ← token do app Plaud (permanente, para rodar localmente)\n"
        "  ou\n"
        "  PLAUD_API_TOKEN=sk-ant-si-...   ← token de sessão Claude Code"
    )


def list_recordings(limit: int = 30) -> list[dict]:
    return json.loads(_call_tool("list_recordings", {"limit": limit}))


def get_recording_detail(file_id: str) -> dict:
    return json.loads(_call_tool("get_recording_detail", {"file_id": file_id}))


def get_transcript(file_id: str) -> str:
    return _call_tool("get_transcript", {"file_id": file_id})


def extract_speakers(transcript: str) -> list[str]:
    names = re.findall(r"\]\s+([^:\n]+):", transcript)
    return sorted(set(n.strip() for n in names if n.strip()))
