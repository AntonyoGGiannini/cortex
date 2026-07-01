"""Backfill: preenche `talk_seconds` em fact_recording_speakers (histórico).

Para cada reunião já registrada, busca no Plaud o tempo de fala por speaker e
atualiza os vínculos existentes (casando pelo speaker_key = nome normalizado).

Uso:
    python backfill_talk_seconds.py            # grava (padrão)
    python backfill_talk_seconds.py --dry-run  # só mostra
"""

import os
import sys
import argparse

from dotenv import load_dotenv
from supabase import create_client

from plaud_client import PlaudClient
from lib.normalize import normalize_name  # só usa re/unicodedata, sem streamlit

load_dotenv()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="não grava, só mostra")
    args = ap.parse_args()
    apply = not args.dry_run

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Configure SUPABASE_URL e SUPABASE_SERVICE_KEY no .env")

    sb = create_client(url, key)
    client = PlaudClient()

    recs = sb.table("fact_recordings").select("id,plaud_id,title").execute().data
    print(f"{len(recs)} reuniões.\n")

    atualizados = sem_match = erros = 0

    for r in recs:
        nome = r.get("title") or r["plaud_id"]
        try:
            speakers = client.get_speakers(r["plaud_id"])
        except Exception as e:  # noqa: BLE001
            erros += 1
            print(f"  [erro] {nome}: {e}")
            continue

        # talk_seconds (segundos) e talk_words por speaker_key (nome normalizado).
        # Soma em caso de colisão de chave (defesa: nunca sobrescrever pedaços).
        talk_by_key: dict[str, dict] = {}
        for s in speakers:
            if not s.get("name"):
                continue
            k = normalize_name(s["name"])
            acc = talk_by_key.setdefault(k, {"talk_seconds": 0, "talk_words": 0})
            acc["talk_seconds"] += int(s.get("talk_seconds") or 0)
            acc["talk_words"] += int(s.get("talk_words") or 0)

        # vínculos existentes desta reunião + speaker_key da pessoa
        links = (
            sb.table("fact_recording_speakers")
            .select("speaker_id, dim_speakers(speaker_key)")
            .eq("recording_id", r["id"])
            .execute()
            .data
        )

        for ln in links:
            key = (ln.get("dim_speakers") or {}).get("speaker_key")
            vals = talk_by_key.get(key)
            if vals is None:
                sem_match += 1
                continue
            ts = vals.get("talk_seconds")
            tw = vals.get("talk_words")
            print(f"  [ok] {nome} :: {key} -> {ts}s · {tw} palavras")
            if apply:
                sb.table("fact_recording_speakers").update(
                    {"talk_seconds": ts, "talk_words": tw}
                ).eq("recording_id", r["id"]).eq(
                    "speaker_id", ln["speaker_id"]
                ).execute()
                atualizados += 1

    print("\n--- Resumo ---")
    print(f"  Vínculos atualizados: {atualizados}")
    print(f"  Sem correspondência de fala: {sem_match}")
    print(f"  Erros: {erros}")
    if not apply:
        print("\n(dry-run — rode sem --dry-run para gravar)")


if __name__ == "__main__":
    main()
