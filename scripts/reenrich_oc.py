"""
Ri-arricchisce tutte le entita OpenCoesione gia' presenti nel DB
chiamando /api/soggetti/<slug>/ per ogni soggetto e popolando
piva, sede, segnali multi-tema, totali.

Usa lo slug derivato da segnali.raw.url salvato dallo scraper originale.
Esegui dopo aver gia' importato i soggetti almeno una volta.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity.opencoesione_beneficiari import _enrich_from_detail


DB_PATH = Path(__file__).parent.parent / "data" / "db" / "bandi.db"


def extract_slug(url: str) -> str | None:
    if not url or "/api/soggetti/" not in url:
        return None
    try:
        return url.split("/api/soggetti/")[1].split("/")[0]
    except (IndexError, AttributeError):
        return None


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Solo entita che NON hanno ancora avuto detail-fetch:
    # mancano segnali oc_n_progetti / oc_costo_pubblico_tot
    rows = conn.execute("""
        SELECT s.entita_id, s.raw, e.tipo, e.nome
        FROM segnali s JOIN entita e ON e.id = s.entita_id
        WHERE s.tipo = 'oc_fondi_strutturali'
          AND NOT EXISTS (
            SELECT 1 FROM segnali s2
            WHERE s2.entita_id = s.entita_id
              AND s2.tipo IN ('oc_n_progetti', 'oc_costo_pubblico_tot')
          )
        GROUP BY s.entita_id
    """).fetchall()

    conn.close()
    print(f"[ReEnrich] {len(rows)} entita OC da processare")

    seen = set()
    n_ok = 0
    n_err = 0
    for i, r in enumerate(rows, 1):
        raw = r["raw"]
        if not raw:
            continue
        try:
            data = json.loads(raw)
            url  = data.get("url")
        except (json.JSONDecodeError, TypeError):
            continue
        slug = extract_slug(url)
        if not slug or slug in seen:
            continue
        seen.add(slug)

        stats = _enrich_from_detail(slug, r["entita_id"], r["tipo"])
        if stats["temi"] > 0 or stats["piva"] or stats["sede"]:
            n_ok += 1
        else:
            n_err += 1

        if i % 25 == 0:
            print(f"[ReEnrich] {i}/{len(rows)}  ok={n_ok} err={n_err}")
        time.sleep(0.4)  # rate-limit polite

    print(f"[ReEnrich] Completato: ok={n_ok} err={n_err} (su {len(rows)} totali)")


if __name__ == "__main__":
    main()
