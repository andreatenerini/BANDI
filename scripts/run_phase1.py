"""
Orchestratore Fase 1 — Massimizzazione fonti gia' implementate.

Esegue in sequenza:
  1. Scrape TED con 10 PRESET_QUERIES, days_back=365, max_pages=100
  2. Scrape OpenCoesione bandi con max_per_tema=2000 su tutti gli 11 temi
  3. Scrape OpenCoesione beneficiari (entita) con max_per_tema=1000
  4. Backfill regione sui nuovi bandi (regex su ente_nome/titolo)
  5. Ricalcolo completo dei match scores
  6. Stats finali

Tempo atteso: 1-3 ore complessive (dominato dalle chiamate API).
Loggato in data/logs/phase1_<timestamp>.log.

Uso:
  python scripts/run_phase1.py
  python scripts/run_phase1.py --skip ted        # salta TED
  python scripts/run_phase1.py --only oc-entita  # solo entita OC

Implementazione minima della Fase 5 del ROADMAP per il caso Fase 1.
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOG_DIR = ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))


def setup_logging(name: str = "phase1") -> logging.Logger:
    log_file = LOG_DIR / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    logger.info(f"Log file: {log_file}")
    return logger


def step(logger, name: str, fn, *args, **kwargs):
    """Esegue uno step misurando tempo, gestendo errori, loggando il risultato."""
    logger.info(f"=== START: {name} ===")
    t0 = time.monotonic()
    try:
        result = fn(*args, **kwargs)
        dt = time.monotonic() - t0
        logger.info(f"=== DONE: {name} in {dt:.1f}s -> {result!r}")
        return ("ok", dt, result)
    except Exception as e:
        dt = time.monotonic() - t0
        logger.exception(f"=== FAIL: {name} after {dt:.1f}s: {e}")
        return ("error", dt, str(e))


def run_ted(logger):
    from scraper.ted_scraper import scrape_ted, PRESET_QUERIES
    from scraper.db import init_db
    init_db()

    total = 0
    for name, query in PRESET_QUERIES.items():
        logger.info(f"  [TED] query={name}")
        n = scrape_ted(query=query, days_back=365, max_pages=100,
                       verbose=False)
        logger.info(f"  [TED]   -> {n} bandi (cumulativi {total + n})")
        total += n
    return total


def run_oc_bandi(logger):
    from scraper.opencoesione_scraper import scrape_opencoesione
    from scraper.db import init_db
    init_db()
    return scrape_opencoesione(max_per_tema=2000, verbose=False)


def run_oc_entita(logger):
    from entity.opencoesione_beneficiari import import_all_temi
    return import_all_temi(max_per_tema=1000, verbose=False)


def run_backfill(logger):
    # Riusa la logica gia' scritta in scripts/backfill_regione.py
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "backfill_regione",
        ROOT / "scripts" / "backfill_regione.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()
    return "completed"


def run_match(logger):
    from matching.run_matching import run_matching
    return run_matching(verbose=False)


def run_stats(logger):
    import sqlite3
    conn = sqlite3.connect(ROOT / "data" / "db" / "bandi.db")
    counts = {}
    for tbl in ("bandi", "entita", "segnali", "match_scores"):
        counts[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    bandi_per_fonte = {
        r[0]: r[1] for r in conn.execute(
            "SELECT fonte, COUNT(*) FROM bandi GROUP BY fonte").fetchall()
    }
    bandi_attivi = conn.execute(
        "SELECT COUNT(*) FROM bandi WHERE stato='attivo'").fetchone()[0]
    conn.close()
    logger.info(f"Bandi totali:    {counts['bandi']}")
    logger.info(f"Bandi attivi:    {bandi_attivi}")
    logger.info(f"Bandi per fonte: {bandi_per_fonte}")
    logger.info(f"Entita:          {counts['entita']}")
    logger.info(f"Segnali:         {counts['segnali']}")
    logger.info(f"Match scores:    {counts['match_scores']}")
    return counts


STEPS = [
    ("ted",       "Scrape TED (10 query, 365gg, 100 pages)",     run_ted),
    ("oc-bandi",  "Scrape OpenCoesione bandi (max 2000/tema)",   run_oc_bandi),
    ("oc-entita", "Scrape OC entita (max 1000/tema)",            run_oc_entita),
    ("backfill",  "Backfill regione sui bandi",                   run_backfill),
    ("match",     "Ricalcolo match_scores",                       run_match),
    ("stats",     "Stats finali",                                 run_stats),
]


def main():
    p = argparse.ArgumentParser(description="Orchestratore Fase 1 BANDI")
    p.add_argument("--skip", action="append", default=[],
                   help="Step da saltare (ripetibile)")
    p.add_argument("--only", action="append", default=[],
                   help="Esegui SOLO questi step (ripetibile)")
    args = p.parse_args()

    logger = setup_logging("phase1")
    started_at = datetime.now(timezone.utc)
    logger.info(f"Pipeline avviata: {started_at.isoformat()}")

    results = []
    for key, desc, fn in STEPS:
        if args.only and key not in args.only:
            logger.info(f"--- SKIP (not in --only): {key}")
            continue
        if key in args.skip:
            logger.info(f"--- SKIP (in --skip): {key}")
            continue
        status, dt, result = step(logger, desc, fn, logger)
        results.append({"step": key, "status": status, "duration_sec": dt})

    ended_at = datetime.now(timezone.utc)
    duration = (ended_at - started_at).total_seconds()
    logger.info(f"Pipeline conclusa in {duration:.0f}s "
                f"({duration / 60:.1f} min)")

    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_err = sum(1 for r in results if r["status"] == "error")
    logger.info(f"Esiti: {n_ok} ok, {n_err} error su {len(results)} step")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
