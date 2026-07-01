"""Backfill / ingestão incremental do FEEDBACK DE PARTICIPAÇÃO (v2 — você).

Para cada reunião em que a pessoa-alvo (CORTEX_ME_KEY) participou e que ainda
não tem feedback, lê o transcript, extrai via Anthropic o que ela fez bem, o
que melhorar (com evidência citável) e um score de influência, e grava em
fact_participation_feedback.

Idempotente: só pega reuniões sem feedback — reruns não duplicam. Bom como
tarefa agendada (diária) conforme novas reuniões entram.

Pré-requisitos no .env:
    SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY
    (opcional) ANTHROPIC_MODEL, PERFIL_MAX_CHARS, CORTEX_ME_KEY

Uso:
    python backfill_feedback.py                 # processa todas as pendentes
    python backfill_feedback.py --limit 3       # só as 3 mais antigas (teste barato)
    python backfill_feedback.py --dry-run       # extrai e mostra, NÃO grava
"""

import sys
import argparse

from lib.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    SUPABASE_SERVICE_KEY,
    ME_SPEAKER_KEY,
)
from lib import participation_feedback as pf


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingestão de feedback de participação (v2).")
    ap.add_argument("--limit", type=int, default=None, help="máx. de reuniões a processar")
    ap.add_argument("--dry-run", action="store_true", help="não grava, só mostra")
    args = ap.parse_args()

    if not SUPABASE_SERVICE_KEY:
        sys.exit("Configure SUPABASE_SERVICE_KEY no .env")
    if not ANTHROPIC_API_KEY:
        sys.exit("Configure ANTHROPIC_API_KEY no .env (necessária para a extração)")

    def progress(i: int, total: int, res: dict) -> None:
        infl = res["influence_score"]
        infl_txt = f"infl {infl}" if infl is not None else "infl —"
        print(f"  [{i}/{total}] {res['title'] or res['recording_id']} — "
              f"{infl_txt} · {res['n_fortes']} forte(s) / {res['n_melhorar']} a melhorar")

    print(f"Alvo: {ME_SPEAKER_KEY} | Modelo: {ANTHROPIC_MODEL}"
          f"{' (DRY-RUN)' if args.dry_run else ''}\n")

    out = pf.process_pending(
        speaker_key=ME_SPEAKER_KEY,
        limit=args.limit,
        dry_run=args.dry_run,
        on_progress=progress,
    )

    if out["reunioes_processadas"] == 0:
        print("Nenhuma reunião pendente de feedback. Tudo em dia. ✅")
        return

    print("\n--- Resumo ---")
    print(f"  Pessoa-alvo:          {out['alvo']}")
    print(f"  Reuniões processadas: {out['reunioes_processadas']}")
    if args.dry_run:
        print("\n(dry-run — rode sem --dry-run para gravar)")


if __name__ == "__main__":
    main()
