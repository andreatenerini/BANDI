"""
Orchestratore scraper -- esegue tutti i bandi in sequenza.
Fonti: TED (EU appalti) + OpenCoesione (PNRR/FESR/FSE+) + MUR (PRIN e ricerca)

Uso:
    python -m scraper.run_all
    python -m scraper.run_all --fast
    python -m scraper.run_all --ted-only
    python -m scraper.run_all --skip-oc
"""
import argparse
import time
from .db import init_db, count_bandi
from .ted_scraper import scrape_ted, PRESET_QUERIES
from .mur_scraper import scrape_mur
from .opencoesione_scraper import scrape_opencoesione

SEP = "-" * 60


def run(
    run_ted: bool = True,
    run_oc:  bool = True,
    run_mur: bool = True,
    fast:    bool = False,
):
    init_db()
    before = count_bandi()
    t0 = time.time()
    results = {}

    # ── MUR (veloce, parte da dati noti) ─────────────────────────────────────
    if run_mur:
        print(f"\n{SEP}")
        print("  MUR -- Ministero dell'Universita e della Ricerca")
        print(SEP)
        results["mur"] = scrape_mur(
            scrape_live=not fast,
            include_known=True,
        )

    # ── OpenCoesione (PNRR / fondi strutturali EU) ────────────────────────────
    if run_oc:
        print(f"\n{SEP}")
        print("  OpenCoesione -- PNRR, FESR, FSE+")
        print(SEP)
        temi_fast = ["ricerca-e-innovazione", "competitivita-imprese"]
        results["opencoesione"] = scrape_opencoesione(
            max_per_tema=20 if fast else 200,
            temi=temi_fast if fast else None,
        )

    # ── TED (appalti EU sopra soglia) ─────────────────────────────────────────
    if run_ted:
        print(f"\n{SEP}")
        print("  TED -- Tenders Electronic Daily (EU)")
        print(SEP)
        queries = (
            {"it_servizi": PRESET_QUERIES["it_servizi"]}
            if fast
            else PRESET_QUERIES
        )
        ted_total = 0
        for name, q in queries.items():
            print(f"\n  Query: {name}")
            n = scrape_ted(
                query=q,
                days_back=30 if fast else 90,
                max_pages=2 if fast else 20,
            )
            ted_total += n
        results["ted"] = ted_total

    # ── Riepilogo ─────────────────────────────────────────────────────────────
    after   = count_bandi()
    elapsed = time.time() - t0
    print(f"\n{SEP}")
    print("  RIEPILOGO")
    print(SEP)
    for src, n in results.items():
        print(f"  {src.upper():<16} {n:>8} bandi scritti")
    print(f"  {'DELTA':<16} {after - before:>8} nuovi nel DB")
    print(f"  {'TOTALE':<16} {after:>8} bandi nel DB")
    print(f"  Tempo         {elapsed:>8.1f}s")
    return after - before


def main():
    p = argparse.ArgumentParser(description="Scraper bandi pubblici")
    p.add_argument("--ted-only", action="store_true")
    p.add_argument("--oc-only",  action="store_true")
    p.add_argument("--mur-only", action="store_true")
    p.add_argument("--skip-ted", action="store_true")
    p.add_argument("--skip-oc",  action="store_true")
    p.add_argument("--skip-mur", action="store_true")
    p.add_argument("--fast",     action="store_true")
    args = p.parse_args()

    only = args.ted_only or args.oc_only or args.mur_only
    run(
        run_ted = (args.ted_only or not only) and not args.skip_ted,
        run_oc  = (args.oc_only  or not only) and not args.skip_oc,
        run_mur = (args.mur_only or not only) and not args.skip_mur,
        fast    = args.fast,
    )


if __name__ == "__main__":
    main()
