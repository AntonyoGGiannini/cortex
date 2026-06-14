"""Servidor MCP Plaud (acesso cru/legado).

Mantido para leitura direta das gravações. O pipeline consolidador NÃO depende
deste servidor; ele usa `plaud_client.PlaudClient` diretamente.
"""

import os
import json

from mcp.server.fastmcp import FastMCP

from server import PlaudClient

mcp = FastMCP("plaud", host="0.0.0.0", stateless_http=True)
client = PlaudClient()


@mcp.tool()
def list_recordings(limit: int = 20) -> str:
    """Lista as gravações do Plaud. Retorna id, nome, duração e data de criação."""
    files = client.list_recordings_page(page=1, page_size=limit)
    result = [client.summarize_listing(f) for f in files]
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_transcript(file_id: str) -> str:
    """Retorna a transcrição completa de uma gravação pelo seu ID."""
    file_data = client.get_detail(file_id)
    text = client.get_transcript_text(file_data)
    return text or "Transcrição não disponível para esta gravação."


@mcp.tool()
def get_summary(file_id: str) -> str:
    """Retorna o resumo de IA gerado pelo Plaud para uma gravação."""
    file_data = client.get_detail(file_id)
    summary = client.get_summary(file_data)
    if summary is None:
        return "Resumo não disponível para esta gravação."
    return json.dumps(summary, ensure_ascii=False, indent=2)


@mcp.tool()
def get_recording_detail(file_id: str) -> str:
    """Retorna todos os metadados de uma gravação (nome, duração, falantes, tags etc)."""
    file_data = client.get_detail(file_id)
    meta = {
        k: v
        for k, v in file_data.items()
        if k not in ("content_list", "embeddings", "download_path_mapping", "pre_download_content_list")
    }
    return json.dumps(meta, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    app = mcp.sse_app()
    uvicorn.run(app, host="0.0.0.0", port=port)