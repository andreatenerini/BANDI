"""
Backfill della colonna `bandi.regione` per i record gia' esistenti.

Strategia: regex su `ente_nome` per estrarre nomi di regione italiani.
Funziona soprattutto per OpenCoesione dove l'ente_nome e' "REGIONE LAZIO",
"REGIONE PUGLIA" etc. Per TED non c'e' segnale territoriale persistito.
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.db import init_db, DB_PATH


REGIONI = [
    "Piemonte", "Valle d'Aosta", "Lombardia", "Trentino-Alto Adige",
    "Veneto", "Friuli-Venezia Giulia", "Liguria", "Emilia-Romagna",
    "Toscana", "Umbria", "Marche", "Lazio", "Abruzzo", "Molise",
    "Campania", "Puglia", "Basilicata", "Calabria", "Sicilia", "Sardegna",
    # Varianti comuni
    "Sicilia",  # "REGIONE SICILIANA"
    "Trentino", "Alto Adige", "Friuli",
]

# pattern: cerca "REGIONE X" o "X" come standalone (case-insensitive)
PATTERN = re.compile(
    r"\b(?:REGIONE\s+)?(" +
    "|".join(re.escape(r).upper() for r in REGIONI) + r"|SICILIANA)\b",
    re.IGNORECASE,
)

ALIAS = {
    "siciliana":              "Sicilia",
    "trentino":               "Trentino-Alto Adige",
    "alto adige":             "Trentino-Alto Adige",
    "friuli":                 "Friuli-Venezia Giulia",
    "valle d'aosta":          "Valle d'Aosta",
    "trentino-alto adige":    "Trentino-Alto Adige",
    "friuli-venezia giulia":  "Friuli-Venezia Giulia",
    "emilia-romagna":         "Emilia-Romagna",
}


def detect_regione(text: str) -> str | None:
    if not text:
        return None
    m = PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1).lower()
    return ALIAS.get(raw, raw.title())


def main():
    init_db()  # assicura che la colonna esista
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, ente_nome, titolo, descrizione FROM bandi "
        "WHERE regione IS NULL"
    ).fetchall()
    print(f"[Backfill] {len(rows)} bandi senza regione")

    n_updated = 0
    for r in rows:
        for src in (r["ente_nome"], r["titolo"], r["descrizione"]):
            reg = detect_regione(src or "")
            if reg:
                conn.execute(
                    "UPDATE bandi SET regione=? WHERE id=?",
                    (reg, r["id"]),
                )
                n_updated += 1
                break
        if n_updated and n_updated % 50 == 0:
            conn.commit()
    conn.commit()

    print(f"[Backfill] regione popolata su {n_updated} bandi")

    print()
    print("Distribuzione regione (top 15):")
    for row in conn.execute(
        "SELECT regione, COUNT(*) AS n FROM bandi "
        "WHERE regione IS NOT NULL GROUP BY regione ORDER BY n DESC LIMIT 15"
    ).fetchall():
        print(f"  {row['regione']:<25} {row['n']:>5}")
    conn.close()


if __name__ == "__main__":
    main()
