"""Backfill / ingestão incremental de MENÇÕES DE PROJETOS/TEMAS.

Para cada tema ativo, avalia as reuniões ainda não vistas (ledger fact_project_scan),
extrai o que cada call trouxe sobre o tema (update, trechos, decisões, to-dos) e
regenera o resumo vivo. Idempotente: só pega o que ainda não foi avaliado.

Serve tanto para o FORWARD (calls novas entram pendentes para os temas ativos)
quanto para o BACKFILL (tema novo entra com todo o histórico pendente). Por padrão
usa o filtro híbrido (PROJ_HYBRID_FILTER): só manda ao LLM as calls que contêm o
nome/alias do tema; corta custo no acervo.

Pré-requisitos no .env:
    SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY
    (opcional) ANTHROPIC_MODEL, PROJ_MAX_CHARS, PROJ_MIN_RELEVANCE, PROJ_HYBRID_FILTER

Uso:
    python backfill_projetos.py                  # todos os temas ativos
    python backfill_projetos.py --project "Onboarding Digital"   # só um tema (por nome)
    python backfill_projetos.py --no-hybrid      # manda todas as calls ao LLM
    python backfill_projetos.py --limit 10       # no máx. 10 calls por tema
    python backfill_projetos.py --dry-run        # extrai e mostra, NÃO grava
"""

import sys
import argparse

from lib.config import ANTHROPIC_API_KEY, SUPABASE_SERVICE_KEY, ANTHROPIC_MODEL
from lib import db, projects


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingestão de menções de projetos/temas.")
    ap.add_argument("--project", type=str, default=None, help="nome do tema (default: todos os ativos)")
    ap.add_argument("--limit", type=int, default=None, help="máx. de reuniões por tema")
    ap.add_argument("--no-hybrid", action="store_true", help="manda todas as calls ao LLM")
    ap.add_argument("--dry-run", action="store_true", help="não grava, só mostra")
    args = ap.parse_args()

    if not SUPABASE_SERVICE_KEY:
        sys.exit("Configure SUPABASE_SERVICE_KEY no .env")
    if not ANTHROPIC_API_KEY:
        sys.exit("Configure ANTHROPIC_API_KEY no .env (necessária para a extração)")

    hybrid = not args.no_hybrid

    if args.project:
        alvo = [
            p for p in db.get_projects()
            if p.get("name", "").lower() == args.project.lower()
        ]
        if not alvo:
            sys.exit(f"Tema não encontrado: {args.project!r}")
    else:
        alvo = db.get_projects(only_active=True)
        if not alvo:
            sys.exit("Nenhum tema ativo cadastrado.")

    print(
        f"Modelo: {ANTHROPIC_MODEL} | Temas: {len(alvo)} | "
        f"Filtro: {'híbrido' if hybrid else 'IA em todas'}"
        f"{' (DRY-RUN)' if args.dry_run else ''}\n"
    )

    tot_men = 0
    tot_llm = 0
    for p in alvo:
        def progress(i, total, res):
            tag = {"mencao": "✓ menção", "sem_mencao": "· sem sinal", "filtrada": "– filtrada"}.get(
                res.get("status"), res.get("status")
            )
            print(f"    [{i}/{total}] {res.get('title') or ''} — {tag}")

        print(f"» {p.get('name')}")
        out = projects.process_project(
            p, hybrid=hybrid, limit=args.limit, dry_run=args.dry_run, on_progress=progress
        )
        tot_men += out["mencoes_novas"]
        tot_llm += out["chamadas_llm"]
        print(
            f"   {out['reunioes_vistas']} vistas · {out['chamadas_llm']} IA · "
            f"{out['filtradas']} filtradas · {out['mencoes_novas']} menções"
            f"{' · resumo atualizado' if out['resumo_atualizado'] else ''}\n"
        )

    print("--- Resumo ---")
    print(f"  Menções novas:     {tot_men}")
    print(f"  Leituras de IA:    {tot_llm}")
    if args.dry_run:
        print("\n(dry-run — rode sem --dry-run para gravar)")


if __name__ == "__main__":
    main()
