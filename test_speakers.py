"""Teste rápido de get_speakers e funções relacionadas."""

from plaud_client import PlaudClient

client = PlaudClient()

# 1. Lista as 5 primeiras gravações
print("=== Gravações ===")
recs = client.list_recordings_page(page=1, page_size=5)
for r in recs:
    print(client.summarize_listing(r))

# 2. Testa get_speakers na primeira com transcrição
file_id = None
for r in recs:
    s = client.summarize_listing(r)
    if s["has_transcript"]:
        file_id = s["id"]
        print(f"\nUsando: {s['name']} ({file_id})")
        break

if not file_id:
    print("\nNenhuma gravação com transcrição nas primeiras 5. Ajuste page_size.")
else:
    print("\n=== Speakers ===")
    speakers = client.get_speakers(file_id)
    for sp in speakers:
        status = "identificado" if sp["identified"] else "genérico"
        nome = f"{sp['original_label']}: {sp['name']}" if sp["name"] else sp["original_label"]
        print(f"  [{status}] {nome} — {sp['segments']} segmentos | first: {sp['first_at']} | talk: {sp['talk_time']}")
