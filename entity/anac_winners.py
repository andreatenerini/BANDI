"""
Estrae aziende aggiudicatarie dai CSV ANAC (campo aggiudicatari).
Usa gli stessi file già scaricati da anac_scraper.py.
Fonte: dati.anticorruzione.it bulk CSV OCDS
"""
import csv
import json
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.config import ANAC_RAW_DIR
from scraper.db import init_db
from entity.entity_db import upsert_entita, upsert_segnale, upsert_contratto_vinto

# Colonne aggiudicatari nel CSV ANAC (formato OCDS)
AWARD_COLS = {
    "awards.suppliers.name":           "nome",
    "awards.suppliers.identifier.id":  "piva",
    "awards.value.amount":             "importo",
    "awards.value.currency":           "valuta",
    "tender.mainProcurementCategory":  "categoria",
    "buyer.name":                      "ente_appaltante",
    "tender.id":                       "cig",
    "date":                            "data",
}


def _parse_award_row(row: dict, year: str) -> list:
    """
    Un'aggiudicazione può avere più fornitori (pipe-separated).
    Restituisce lista di (entita_dict, contratto_dict).
    """
    nome_raw = row.get("awards.suppliers.name", "").strip()
    piva_raw = row.get("awards.suppliers.identifier.id", "").strip()

    if not nome_raw:
        return []

    nomi  = [n.strip() for n in nome_raw.split("|") if n.strip()]
    pivas = [p.strip() for p in piva_raw.split("|") if p.strip()]

    importo = None
    raw_imp = row.get("awards.value.amount", "").strip()
    if raw_imp:
        try:
            importo = float(raw_imp.replace(",", "."))
        except ValueError:
            pass

    cig  = row.get("tender.id", "").strip()
    data = row.get("date", "")[:4]
    anno = int(data) if data.isdigit() else None
    cpv  = row.get("cpv_division", row.get("tender.mainProcurementCategory", ""))

    results = []
    for i, nome in enumerate(nomi):
        piva = pivas[i] if i < len(pivas) else None
        results.append((
            {
                "tipo":   "azienda",
                "nome":   nome,
                "piva":   piva,
                "paese":  "IT",
            },
            {
                "id":               f"ANAC-AWD-{cig}-{i}" if cig else
                                    f"ANAC-AWD-{year}-{hashlib.md5(nome.encode()).hexdigest()[:8]}-{i}",
                "cpv":              cpv[:8] if cpv else None,
                "importo":          importo / len(nomi) if importo else None,
                "ente_appaltante":  row.get("buyer.name", "").strip() or None,
                "anno":             anno,
                "fonte":            "ANAC",
            }
        ))
    return results


def import_anac_winners(
    years: list = None,
    max_rows: int = 100_000,
    verbose: bool = True,
) -> int:
    """
    Importa aggiudicatari dai CSV ANAC già scaricati.
    Richiede che scrape_anac() sia già stato eseguito.

    Args:
        years:    anni da elaborare (default: tutti i CSV presenti)
        max_rows: limite righe per anno
        verbose:  stampa progressi

    Returns:
        Numero di entità nuove/aggiornate
    """
    if years is None:
        years = [p.stem.split("_")[1]
                 for p in ANAC_RAW_DIR.glob("anac_*.csv")]

    total = 0

    for year in years:
        csv_path = ANAC_RAW_DIR / f"anac_{year}.csv"
        if not csv_path.exists():
            print(f"[ANAC-W] {year}: CSV non trovato ({csv_path}), skip.")
            print(f"         Esegui prima: python -m scraper.anac_scraper")
            continue

        count = 0
        try:
            with open(csv_path, encoding="utf-8-sig", newline="",
                      errors="replace") as f:
                reader = csv.DictReader(f, delimiter=";")
                for i, row in enumerate(reader):
                    if max_rows and i >= max_rows:
                        break

                    for entita, contratto in _parse_award_row(row, year):
                        eid = upsert_entita(entita)
                        contratto["entita_id"] = eid

                        # Segnale: categoria CPV storica (peso alto)
                        if contratto.get("cpv"):
                            upsert_segnale(
                                eid, "cpv_vinto", contratto["cpv"],
                                peso=3.0, fonte="ANAC",
                                data_rilevazione=str(contratto.get("anno")),
                                raw={"cig": contratto["id"]}
                            )

                        try:
                            upsert_contratto_vinto(contratto)
                            count += 1
                        except Exception:
                            pass

                    if verbose and count % 10_000 == 0 and count > 0:
                        print(f"[ANAC-W] {year}: {count} aggiudicatari importati...")

        except Exception as e:
            print(f"[ANAC-W] Errore lettura {year}: {e}")
            continue

        print(f"[ANAC-W] {year}: {count} aggiudicatari salvati")
        total += count

    print(f"[ANAC-W] Totale: {total} aggiudicatari")
    return total


if __name__ == "__main__":
    init_db()
    import_anac_winners(max_rows=20_000)
