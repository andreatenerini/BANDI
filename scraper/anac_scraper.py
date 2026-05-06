"""
Scraper ANAC -- Autorita Nazionale Anticorruzione
Fonte: dati.anticorruzione.it/opendata
Metodo: download bulk CSV (l'API REST e bloccata da WAF).

NOTA: Il sito ANAC blocca le richieste automatizzate via WAF.
Se il download automatico fallisce, scarica manualmente il file da:
  https://dati.anticorruzione.it/opendata/dataset/ocds-appalti-ordinari-ANNO
e posizionalo in: data/raw/anac/anac_ANNO.csv  (estratto dallo ZIP)
"""
import csv
import io
import json
import time
import zipfile
import requests
from pathlib import Path
from datetime import datetime

from .config import ANAC_RAW_DIR, HEADERS, TIMEOUT
from .db import upsert_bando, init_db

ANAC_RAW_DIR.mkdir(parents=True, exist_ok=True)

# Dataset ANAC -- URL aggiornati (pattern da verificare sul portale)
# Il portale blocca l'accesso automatico: in caso di 404/WAF, scarica manualmente
# da https://dati.anticorruzione.it/opendata e salva come data/raw/anac/anac_ANNO.csv
ANAC_DATASETS = {
    "appalti_2023": "https://dati.anticorruzione.it/opendata/download/dataset/appalti-ocds/filesystem/appalti_ocds_2023.csv.zip",
    "appalti_2024": "https://dati.anticorruzione.it/opendata/download/dataset/appalti-ocds/filesystem/appalti_ocds_2024.csv.zip",
    "appalti_2025": "https://dati.anticorruzione.it/opendata/download/dataset/appalti-ocds/filesystem/appalti_ocds_2025.csv.zip",
    "appalti_2026": "https://dati.anticorruzione.it/opendata/download/dataset/appalti-ocds/filesystem/appalti_ocds_2026.csv.zip",
}

MANUAL_DOWNLOAD_MSG = """
[ANAC] DOWNLOAD MANUALE RICHIESTO
  Il portale ANAC blocca i download automatici.
  Passaggi:
  1. Apri nel browser: https://dati.anticorruzione.it/opendata
  2. Cerca "appalti OCDS {year}" e scarica il CSV/ZIP
  3. Estrai il CSV e salvalo come: {csv_path}
  4. Ri-esegui lo scraper
"""

# Colonne rilevanti nel CSV ANAC OCDS
COLONNE_ANAC = {
    "ocid":                          "id_ocid",
    "tender.id":                     "cig",
    "tender.title":                  "titolo",
    "tender.description":            "descrizione",
    "tender.mainProcurementCategory":"categoria",
    "tender.value.amount":           "importo",
    "tender.value.currency":         "valuta",
    "tender.tenderPeriod.endDate":   "scadenza",
    "tender.status":                 "stato_raw",
    "buyer.name":                    "ente_nome",
    "buyer.address.countryName":     "ente_paese",
    "planning.budget.amount.amount": "budget",
    "date":                          "data_pubblicazione",
}


def _categoria_to_tipo(cat: str) -> str:
    m = {
        "services": "appalto_servizi",
        "goods":    "appalto_forniture",
        "works":    "appalto_lavori",
    }
    return m.get(str(cat).lower(), "appalto_servizi")


def _parse_row(row: dict, year: str) -> dict | None:
    """Trasforma una riga CSV ANAC nel formato comune."""
    cig    = row.get("tender.id", "").strip()
    titolo = row.get("tender.title", "").strip()
    if not cig and not titolo:
        return None

    bid = f"ANAC-{cig}" if cig else f"ANAC-{year}-{hash(titolo) & 0xFFFFFF}"

    importo = None
    for field in ("tender.value.amount", "planning.budget.amount.amount"):
        raw = row.get(field, "").strip()
        if raw:
            try:
                importo = float(raw.replace(",", "."))
                break
            except ValueError:
                pass

    scadenza = row.get("tender.tenderPeriod.endDate", "").strip()
    if scadenza:
        scadenza = scadenza[:10]

    stato_raw = row.get("tender.status", "").lower()
    stato = "attivo" if "active" in stato_raw or "planned" in stato_raw else "scaduto"

    categoria = row.get("tender.mainProcurementCategory", "services")
    tipo = _categoria_to_tipo(categoria)

    return {
        "id":                 bid,
        "fonte":              "ANAC",
        "tipo":               tipo,
        "titolo":             titolo[:500] if titolo else None,
        "descrizione":        row.get("tender.description", "")[:2000] or None,
        "ente_nome":          row.get("buyer.name", "").strip() or None,
        "ente_paese":         "IT",
        "importo_min":        None,
        "importo_max":        None,
        "importo_stimato":    importo,
        "valuta":             row.get("tender.value.currency", "EUR") or "EUR",
        "data_pubblicazione": row.get("date", "")[:10] or None,
        "data_scadenza":      scadenza or None,
        "stato":              stato,
        "url_originale":      f"https://dati.anticorruzione.it/opendata",
        "url_pdf":            None,
        "cpv_codes":          [],
        "settori":            [categoria] if categoria else [],
        "destinatari":        ["aziende"],
        "_raw":               row,
    }


def _download_and_extract(url: str, year: str, verbose: bool = True) -> Path | None:
    """Scarica lo ZIP ANAC e restituisce il percorso del CSV estratto."""
    zip_path = ANAC_RAW_DIR / f"anac_{year}.csv.zip"
    csv_path = ANAC_RAW_DIR / f"anac_{year}.csv"

    if csv_path.exists():
        if verbose:
            print(f"[ANAC] {year}: file gia presente -> {csv_path}")
        return csv_path

    if verbose:
        print(f"[ANAC] Download {year}: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=120, stream=True)
        r.raise_for_status()
        # Rileva WAF rejection (restituisce 200 con HTML)
        content_type = r.headers.get("Content-Type", "")
        if "text/html" in content_type:
            print(f"[ANAC] {year}: accesso bloccato da WAF.")
            print(MANUAL_DOWNLOAD_MSG.format(year=year, csv_path=csv_path))
            return None
    except requests.HTTPError as e:
        print(f"[ANAC] {year} non disponibile ({e.response.status_code}).")
        print(MANUAL_DOWNLOAD_MSG.format(year=year, csv_path=csv_path))
        return None
    except requests.RequestException as e:
        print(f"[ANAC] Errore connessione: {e}")
        return None

    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            names = [n for n in z.namelist() if n.endswith(".csv")]
            if not names:
                print(f"[ANAC] {year}: nessun CSV nello ZIP")
                zip_path.unlink(missing_ok=True)
                return None
            z.extract(names[0], ANAC_RAW_DIR)
            extracted = ANAC_RAW_DIR / names[0]
            extracted.rename(csv_path)
    except zipfile.BadZipFile:
        print(f"[ANAC] {year}: ZIP corrotto (possibile WAF)")
        zip_path.unlink(missing_ok=True)
        print(MANUAL_DOWNLOAD_MSG.format(year=year, csv_path=csv_path))
        return None

    zip_path.unlink(missing_ok=True)
    if verbose:
        print(f"[ANAC] {year}: estratto -> {csv_path}")
    return csv_path


def scrape_anac(
    years: list = None,
    max_rows: int = 50_000,
    verbose: bool = True,
) -> int:
    """
    Scarica i CSV ANAC e importa i bandi nel DB.

    Args:
        years:    lista anni da importare (default: [2025, 2026])
        max_rows: limite righe per anno (None = tutto)
        verbose:  stampa progressi

    Returns:
        Numero totale di bandi importati
    """
    if years is None:
        years = ["2025", "2026"]

    total = 0

    for year in years:
        url = ANAC_DATASETS.get(f"appalti_{year}")
        if not url:
            print(f"[ANAC] Anno {year} non in configurazione")
            continue

        csv_path = _download_and_extract(url, year, verbose)
        if not csv_path:
            continue

        count = 0
        errors = 0
        try:
            with open(csv_path, encoding="utf-8-sig", newline="", errors="replace") as f:
                reader = csv.DictReader(f, delimiter=";")
                for i, row in enumerate(reader):
                    if max_rows and i >= max_rows:
                        if verbose:
                            print(f"[ANAC] {year}: limite {max_rows} righe raggiunto")
                        break
                    bando = _parse_row(row, year)
                    if bando:
                        try:
                            upsert_bando(bando)
                            count += 1
                        except Exception as e:
                            errors += 1
                            if errors <= 3:
                                print(f"[ANAC] Errore insert: {e}")
                    if verbose and count % 5000 == 0 and count > 0:
                        print(f"[ANAC] {year}: {count} bandi importati...")
        except Exception as e:
            print(f"[ANAC] Errore lettura CSV {year}: {e}")
            continue

        print(f"[ANAC] {year}: completato - {count} bandi, {errors} errori")
        total += count

    print(f"[ANAC] Totale importato: {total} bandi")
    return total


if __name__ == "__main__":
    init_db()
    scrape_anac(years=["2026"], max_rows=10_000)
