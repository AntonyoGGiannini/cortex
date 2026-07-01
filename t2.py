import json
import sys
import server
import os
from mcp.server.fastmcp import FastMCP
from plaud_client import PlaudClient

sys.stdout.reconfigure(encoding="utf-8")

mcp = FastMCP("plaud", host="0.0.0.0", stateless_http=True)

client = PlaudClient()

files = client.list_recordings_page(page=1, page_size=20)

result = [client.summarize_listing(f) for f in files]

gravacoes_json = json.dumps(result, ensure_ascii=False, indent=2)
gravacoes = json.loads(gravacoes_json)

