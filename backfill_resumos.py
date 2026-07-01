"""Backfill: preenche `transcript` e substitui `summary` das reuniões JÁ salvas.

Para cada gravação em fact_recordings:
  - busca a transcrição no Plaud -> grava em `transcript`;
  - busca o data_content (markdown) do pre_download_content_list -> grava em `summary`.

ATENÇÃO: sobrescreve `summary` e `transcript`. Rode primeiro em dry-run.

Uso:
    python backfill_resumos.py            # grava no Supabase (padrão)
    python backfill_resumos.py --dry-run  # só mostra o que faria, não grava
"""

import os
import sys
import argparse

from dotenv import load_dotenv
from supabase import create_client
from plaud_client import PlaudClient

load_dotenv()


def extract_summary_md(file_data: dict) -> str:
    """data_content do bloco de resumo (data_id contém 'sum'); fallback p/ o 1º."""
    pre = file_data.get("pre_download_content_list") or []
    fallback = ""
    for it in pre:
        if not isinstance(it, dict):
            continue
        tipo = str(it.get("data_id") or "").split(":")[0].lower()
        content = it.get("data_content") or ""
        if "sum" in tipo and content:
            return content
        if not fallback and content:
            fallback = content
    return fallback


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="não grava, só mostra o que faria")
    args = ap.parse_args()
    apply = not args.dry_run

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Configure SUPABASE_URL e SUPABASE_SERVICE_KEY no .env")

    sb = create_client(url, key)
    client = PlaudClient()

    rows = (
        sb.table("fact_recordings")
        .select("id,plaud_id,title")
        .execute()
        .data
    )
    print(f"{len(rows)} reuniões registradas.\n")

    atualizadas = sem_dados = erros = 0

    for r in rows:
        nome = r.get("title") or r["plaud_id"]
        try:
            fd = client.get_detail(r["plaud_id"])
            summary_md = extract_summary_md(fd)
            transcript = client.get_transcript_text(fd)
        except Exception as e:  # noqa: BLE001
            erros += 1
            print(f"  [erro] {nome}: {e}")
            continue

        payload = {}
        if summary_md:
            payload["summary"] = summary_md
        if transcript:
            payload["transcript"] = transcript

        if not payload:
            sem_dados += 1
            print(f"  [sem resumo/transcrição no Plaud] {nome}")
            continue

        partes = []
        if "summary" in payload:
            partes.append(f"resumo {len(summary_md)}c")
        if "transcript" in payload:
            partes.append(f"transcript {len(transcript)}c")
        print(f"  [ok] {nome} — {', '.join(partes)}")

        if apply:
            sb.table("fact_recordings").update(payload).eq("id", r["id"]).execute()
            atualizadas += 1

    print("\n--- Resumo ---")
    if apply:
        print(f"  Atualizadas: {atualizadas}")
    else:
        print(f"  Atualizariam: {len(rows) - sem_dados - erros}")
    print(f"  Sem dados no Plaud: {sem_dados}")
    print(f"  Erros: {erros}")
    if not apply:
        print("\n(dry-run — rode sem --dry-run para gravar)")


if __name__ == "__main__":
    main()
