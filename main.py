"""
BANDI -- punto di ingresso principale.

Uso rapido:
    python main.py --init           inizializza il DB
    python main.py --bandi          scraping bandi (TED+OpenCoesione+MUR)
    python main.py --entita         scraping entita (OpenAlex+CORDIS+OC beneficiari)
    python main.py --match          calcola match bandi -> entita
    python main.py --all            tutto in sequenza
    python main.py --fast --all     test rapido (limiti ridotti)
    python main.py --stats          mostra conteggi DB
    python main.py --show BANDO_ID  mostra top match per un bando
"""
import argparse
import sys
from pathlib import Path

# Forza UTF-8 su Windows (cp1252 non regge caratteri italiani/unicode)
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

from scraper.db import init_db, count_bandi, get_conn
from entity.entity_db import count_entita


def stats():
    conn = get_conn()
    n_bandi    = conn.execute("SELECT COUNT(*) FROM bandi").fetchone()[0]
    n_entita   = conn.execute("SELECT COUNT(*) FROM entita").fetchone()[0]
    n_segnali  = conn.execute("SELECT COUNT(*) FROM segnali").fetchone()[0]
    n_contratti= conn.execute("SELECT COUNT(*) FROM contratti_vinti").fetchone()[0]
    n_pubbl    = conn.execute("SELECT COUNT(*) FROM pubblicazioni").fetchone()[0]
    n_match    = conn.execute("SELECT COUNT(*) FROM match_scores").fetchone()[0]
    conn.close()

    per_fonte = get_conn().execute(
        "SELECT fonte, COUNT(*) as n FROM bandi GROUP BY fonte ORDER BY n DESC"
    ).fetchall()

    SEP = "-" * 50
    print(f"\n{SEP}")
    print("  DATABASE STATS")
    print(SEP)
    print(f"  Bandi:         {n_bandi:>8,}")
    for row in per_fonte:
        print(f"    {row['fonte']:<10}   {row['n']:>8,}")
    print(f"  Entita:        {n_entita:>8,}")
    print(f"  Segnali:       {n_segnali:>8,}")
    print(f"  Contratti:     {n_contratti:>8,}")
    print(f"  Pubblicazioni: {n_pubbl:>8,}")
    print(f"  Match scores:  {n_match:>8,}")
    print(SEP)


def main():
    p = argparse.ArgumentParser(description="BANDI — sistema raccolta e matching bandi pubblici")
    p.add_argument("--init",   action="store_true", help="Inizializza il DB")
    p.add_argument("--bandi",  action="store_true", help="Scraping bandi")
    p.add_argument("--entita", action="store_true", help="Scraping entita")
    p.add_argument("--match",  action="store_true", help="Calcola match bandi -> entita")
    p.add_argument("--all",    action="store_true", help="Tutto (bandi + entita + match)")
    p.add_argument("--stats",  action="store_true", help="Statistiche DB")
    p.add_argument("--show",       type=str, default=None, metavar="BANDO_ID",
                   help="Mostra top match per un bando")
    p.add_argument("--for-entity", type=str, default=None, metavar="NOME_O_ID",
                   help="Mostra bandi piu' rilevanti per una entita")
    p.add_argument("--fast",   action="store_true", help="Limiti ridotti (test)")
    args = p.parse_args()

    if not any([args.init, args.bandi, args.entita, args.match,
                args.all, args.stats, args.show, args.for_entity]):
        p.print_help()
        return

    if args.init or args.bandi or args.entita or args.all:
        init_db()

    if args.bandi or args.all:
        from scraper.run_all import run as run_bandi
        run_bandi(fast=args.fast)

    if args.entita or args.all:
        from entity.run_all import run as run_entita
        run_entita(fast=args.fast)

    if args.match or args.all:
        from matching.run_matching import run_matching
        run_matching(verbose=True)

    if args.show:
        from matching.run_matching import show_matches
        show_matches(args.show)
        return

    if args.for_entity:
        from matching.run_matching import show_entity_bandi
        show_entity_bandi(args.for_entity)
        return

    if args.stats or args.bandi or args.entita or args.match or args.all:
        stats()


if __name__ == "__main__":
    main()
