import os
import json
import re
import requests

_MCP_URL = (
    "https://api.anthropic.com/v2/ccr-sessions/cse_01763jZd33pJiwWaUcDNxNJd/mcp"
    "?mcp_url=https%3A%2F%2Fplaud-production.up.railway.app%2Fsse"
    "&mcp_server_id=41123f61-4ab7-5aa0-91c8-c29b77fcb683"
    "&toolbox_mcp_server_id=49263282-122e-40a0-84e6-86412d28e703"
)
_SESSION_UUID = "cse_01763jZd33pJiwWaUcDNxNJd"
_MCP_SERVER_ID = "49263282-122e-40a0-84e6-86412d28e703"
_TOKEN_FILE = "/home/claude/.claude/remote/.session_ingress_token"


def _get_token() -> str:
    token = os.environ.get("PLAUD_API_TOKEN")
    if token:
        return token
    with open(_TOKEN_FILE) as f:
        return f.read().strip()


def _call_tool(name: str, arguments: dict) -> str:
    headers = {
        "Authorization": f"Bearer {_get_token()}",
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
    resp = requests.post(_MCP_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()

    for line in resp.text.splitlines():
        if line.startswith("data: "):
            data = json.loads(line[6:])
            result = data.get("result", {})
            if result.get("isError"):
                raise RuntimeError(result["content"][0]["text"])
            return result["content"][0]["text"]

    raise ValueError("Nenhum dado retornado pelo MCP")


def list_recordings(limit: int = 30) -> list[dict]:
    return json.loads(_call_tool("list_recordings", {"limit": limit}))


def get_recording_detail(file_id: str) -> dict:
    return json.loads(_call_tool("get_recording_detail", {"file_id": file_id}))


def get_transcript(file_id: str) -> str:
    return _call_tool("get_transcript", {"file_id": file_id})


def extract_speakers(transcript: str) -> list[str]:
    names = re.findall(r"\]\s+([^:\n]+):", transcript)
    return sorted(set(n.strip() for n in names if n.strip()))
