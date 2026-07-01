"""Backfill / ingestão incremental do PERFIL COMPORTAMENTAL dos speakers.

Processa as reuniões ainda não analisadas (behavior_processed_at IS NULL):
para cada uma, extrai observações por participante via Anthropic (com evidência
citável), grava em fact_speaker_observations, marca como processada e recalcula
os perfis agregados (dim_speaker_profile).

Idempotente: só pega pendentes, então reruns não duplicam. Use como tarefa
agendada (diária) para abastecer a análise conforme novas reuniões entram.

Pré-requisitos no .env:
    SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY
    (opcional) ANTHROPIC_MODEL, PERFIL_MAX_CHARS, PERFIL_MIN_TALK_SECONDS

Uso:
    python backfill_perfil.py                 # processa todas as pendentes
    python backfill_perfil.py --limit 5       # processa só as 5 mais antigas
    python backfill_perfil.py --dry-run       # extrai e mostra, NÃO grava
"""

import sys
import argparse

from lib.config import ANTHROPIC_API_KEY, SUPABASE_SERVICE_KEY, ANTHROPIC_MODEL
from lib import db, profiling


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingestão de perfil comportamental.")
    ap.add_argument("--limit", type=int, default=None, help="máx. de reuniões a processar")
    ap.add_argument("--dry-run", action="store_true", help="não grava, só mostra")
    args = ap.parse_args()

    if not SUPABASE_SERVICE_KEY:
        sys.exit("Configure SUPABASE_SERVICE_KEY no .env")
    if not ANTHROPIC_API_KEY:
        sys.exit("Configure ANTHROPIC_API_KEY no .env (necessária para a extração)")

    pend = db.get_pending_recordings(limit=args.limit)
    if not pend:
        print("Nenhuma reunião pendente. Tudo em dia. ✅")
        return

    print(f"Modelo: {ANTHROPIC_MODEL} | Pendentes a processar: {len(pend)}"
          f"{' (DRY-RUN)' if args.dry_run else ''}\n")

    def progress(i: int, total: int, res: dict) -> None:
        if res.get("status") == "aguardando_identificacao":
            quem = ", ".join(res.get("bloqueando") or []) or "speakers não identificados"
            print(f"  [{i}/{total}] {res['title']} — ⏸ aguardando identificação ({quem})")
        else:
            print(f"  [{i}/{total}] {res['title'] or res['recording_id']} — "
                  f"{res['n_obs']} obs · {res['participantes']} participantes")

    out = profiling.process_pending(
        limit=args.limit, dry_run=args.dry_run, on_progress=progress
    )

    print("\n--- Resumo ---")
    print(f"  Reuniões processadas:                  {out['reunioes_processadas']}")
    print(f"  Aguardando identificação dos speakers: {out['aguardando_identificacao']}")
    print(f"  Observações geradas:                   {out['observacoes']}")
    if not args.dry_run:
        print(f"  Perfis recalculados:                   {out['perfis_recalculados']}")
    else:
        print("\n(dry-run — rode sem --dry-run para gravar)")


if __name__ == "__main__":
    main()
