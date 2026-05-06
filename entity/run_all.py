"""
Orchestratore entita -- popola il DB con profili da OpenAlex, CORDIS, OpenCoesione, GitHub.

Uso:
    python -m entity.run_all
    python -m entity.run_all --fast
    python -m entity.run_all --source openalex
"""
import argparse
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.db import init_db
from entity.entity_db import count_entita
from entity.openalex import scrape_openalex_institutions, scrape_openalex_authors
from entity.cordis import scrape_cordis
from entity.opencoesione_beneficiari import import_all_temi as import_oc_beneficiari
from entity.github_scraper import scrape_github_orgs, GITHUB_QUERIES

SEP = "-" * 60


def run(
    run_openalex: bool = True,
    run_cordis:   bool = True,
    run_oc:       bool = True,
    run_github:   bool = False,
    fast:         bool = False,
):
    init_db()
    before = count_entita()
    t0     = time.time()
    results = {}

    if run_openalex:
        print(f"\n{SEP}")
        print("  OpenAlex -- ricercatori e istituzioni italiane")
        print(SEP)
        n_inst = scrape_openalex_institutions(max_inst=50 if fast else 200)
        n_auth = scrape_openalex_authors(max_authors=50 if fast else 500)
        results["openalex"] = n_inst + n_auth

    if run_cordis:
        print(f"\n{SEP}")
        print("  CORDIS / OpenAIRE -- organizzazioni EU (IT)")
        print(SEP)
        results["cordis"] = scrape_cordis(max_projects=50 if fast else 300)

    if run_oc:
        print(f"\n{SEP}")
        print("  OpenCoesione -- beneficiari PNRR/FESR/FSE+")
        print(SEP)
        results["opencoesione"] = import_oc_beneficiari(
            max_per_tema=50 if fast else 500,
        )

    if run_github:
        print(f"\n{SEP}")
        print("  GitHub -- organizzazioni tech italiane")
        print(SEP)
        gh_total = 0
        for name, q in GITHUB_QUERIES.items():
            n = scrape_github_orgs(q, max_orgs=20 if fast else 50)
            gh_total += n
        results["github"] = gh_total

    after   = count_entita()
    elapsed = time.time() - t0
    print(f"\n{SEP}")
    print("  RIEPILOGO ENTITA")
    print(SEP)
    for src, n in results.items():
        print(f"  {src.upper():<16} {n:>8} entita scritte")
    print(f"  {'DELTA':<16} {after - before:>8} nuove nel DB")
    print(f"  {'TOTALE':<16} {after:>8} entita nel DB")
    print(f"  Tempo         {elapsed:>8.1f}s")
    return after - before


def main():
    p = argparse.ArgumentParser(description="Scraper entita")
    p.add_argument("--source", choices=["openalex", "cordis", "oc", "github"])
    p.add_argument("--fast",   action="store_true")
    p.add_argument("--github", action="store_true")
    args = p.parse_args()

    only = args.source is not None
    run(
        run_openalex = (not only or args.source == "openalex"),
        run_cordis   = (not only or args.source == "cordis"),
        run_oc       = (not only or args.source == "oc"),
        run_github   = args.github or (not only and args.source == "github"),
        fast         = args.fast,
    )


if __name__ == "__main__":
    main()
