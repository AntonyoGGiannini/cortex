"""Explorador da estrutura de dados da API Plaud.

Roda localmente e imprime tudo que for relevante para identificar
onde ficam os nomes reais dos speakers.
"""

import json
from plaud_client import PlaudClient

client = PlaudClient()

# ── 1. Pega a primeira gravação disponível ──────────────────────────────────
recs = client.list_recordings_page(page=1, page_size=10)
if not recs:
    print("Nenhuma gravação encontrada.")
    exit()

# Prefere uma com transcrição
file_id = None
for r in recs:
    s = client.summarize_listing(r)
    if s["has_transcript"]:
        file_id = s["id"]
        print(f"Usando: {s['name']} | id={file_id}\n")
        break

if not file_id:
    file_id = client.summarize_listing(recs[0])["id"]
    print(f"Sem transcrição, usando: {file_id}\n")

file_data = client.get_detail(file_id)

# ── 2. Chaves de topo do file_data ─────────────────────────────────────────
print("=" * 60)
print("CHAVES DE TOPO DO FILE_DATA")
print("=" * 60)
for k, v in file_data.items():
    if k in ("content_list", "embeddings", "download_path_mapping", "pre_download_content_list"):
        print(f"  {k}: [omitido — {len(v) if isinstance(v, list) else '?'} itens]")
    else:
        snippet = json.dumps(v, ensure_ascii=False)
        print(f"  {k}: {snippet[:300]}")

# ── 3. extra_data completo ──────────────────────────────────────────────────
print("\n" + "=" * 60)
print("EXTRA_DATA COMPLETO")
print("=" * 60)
extra = file_data.get("extra_data") or {}
print(json.dumps(extra, ensure_ascii=False, indent=2))

# ── 4. content_list — só data_type e task_status ───────────────────────────
print("\n" + "=" * 60)
print("CONTENT_LIST — tipos disponíveis")
print("=" * 60)
for item in file_data.get("content_list", []):
    print(f"  data_type={item.get('data_type')!r:25} task_status={item.get('task_status')}")

# ── 5. Primeiros 5 segmentos da transcrição ────────────────────────────────
print("\n" + "=" * 60)
print("SEGMENTOS DE TRANSCRIÇÃO (primeiros 5)")
print("=" * 60)
segs = client.get_transcript_segments(file_data)
for seg in segs[:5]:
    print(json.dumps(seg, ensure_ascii=False, indent=2))

# ── 6. Busca em todo o file_data por palavras-chave de speaker ────────────
print("\n" + "=" * 60)
print("BUSCA POR CHAVES RELACIONADAS A SPEAKER")
print("=" * 60)
keywords = ("speaker", "spk", "name", "person", "participant", "member", "user", "label", "alias")

def search_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = f"{path}.{k}" if path else k
            if any(kw in k.lower() for kw in keywords):
                print(f"  {full}: {json.dumps(v, ensure_ascii=False)[:200]}")
            search_keys(v, full)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):  # só primeiros 3
            search_keys(item, f"{path}[{i}]")

# exclui content_list para não poluir
slim = {k: v for k, v in file_data.items()
        if k not in ("content_list", "embeddings", "download_path_mapping", "pre_download_content_list")}
search_keys(slim)
