"""
Scraper EU Funding & Tenders Portal — call aperte/forthcoming.
API: https://api.tech.ec.europa.eu/search-api (apiKey="SEDIA" pubblica).

Mappa il formato SEDIA al formato bando del DB:
  - id           = "EU-FT-<reference>"
  - fonte        = "EU-FT"
  - tipo         = ricerca_europea / formazione / incentivo_imprese
  - data_scadenza = metadata.deadlineDate
  - stato        = "attivo" se status in (open=31094502, forthcoming=31094501)
  - url          = result.url

Uso:
    python -m scraper.eu_ft_scraper                # bandi attivi (default)
    python -m scraper.eu_ft_scraper --max 200      # max N record
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import date
from html import unescape
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scraper.db import init_db, upsert_bando  # noqa: E402

API_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
HDR = {
    "User-Agent": "Mozilla/5.0 BANDI-scraper",
    "Content-Type": "application/json",
}
API_KEY = "SEDIA"

# Status code SEDIA -> stato bando
STATUS_FORTHCOMING = "31094501"
STATUS_OPEN        = "31094502"
STATUS_CLOSED      = "31094503"
ATTIVI = {STATUS_FORTHCOMING, STATUS_OPEN}

# Mapping tipo intervention -> tipo bando DB
TIPO_MAP = [
    ("research",       "ricerca_europea"),
    ("innovation",     "ricerca_europea"),
    ("training",       "formazione"),
    ("erasmus",        "formazione"),
    ("eic",            "incentivo_imprese"),
    ("digital",        "incentivo_imprese"),
]

# Keyword EU -> settori IT (lookup a substringa)
SETTORI_KW = [
    (("research", "ricerc"),                     "ricerca"),
    (("innovation", "innovaz"),                  "innovazione"),
    (("digital", "ict", "data"),                 "digitale"),
    (("environment", "climate", "green"),        "ambiente"),
    (("energy", "renewable"),                    "energia"),
    (("health", "medical", "pharma"),            "sanita"),
    (("education", "training", "teaching"),      "formazione"),
    (("culture", "creative", "art"),             "cultura"),
    (("transport", "mobility"),                  "trasporti"),
    (("infrastructure", "construction"),         "infrastrutture"),
    (("social", "inclusion"),                    "sociale"),
    (("space",),                                 "ricerca"),
    (("biotechnology", "biology"),               "scienze_vita"),
]


def _strip_html(s: str) -> str:
    """Rimuove tag HTML e normalizza spazi (descrizioni HTML lunghe)."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _first(meta: dict, key: str, default=""):
    v = meta.get(key, [])
    if isinstance(v, list) and v:
        return v[0]
    return v if v else default


def _infer_tipo(types_action: str, framework: str = "") -> str:
    s = (types_action + " " + framework).lower()
    for needle, tipo in TIPO_MAP:
        if needle in s:
            return tipo
    return "ricerca_europea"


def _infer_settori(keywords: list, title: str = "") -> list:
    text = " ".join(keywords or []) + " " + (title or "")
    text = text.lower()
    out = set()
    for needles, settore in SETTORI_KW:
        if any(n in text for n in needles):
            out.add(settore)
    return list(out) or ["ricerca"]


def _parse_result(r: dict) -> dict | None:
    md = r.get("metadata") or {}
    status = _first(md, "status")
    if status not in ATTIVI:
        return None  # solo bandi attivi

    reference = r.get("reference") or _first(md, "REFERENCE")
    if not reference:
        return None

    title = _first(md, "title") or _first(md, "callTitle") or r.get("title", "")
    summary = r.get("summary") or r.get("content", "")
    descr_html = _first(md, "descriptionByte", "")
    descr = _strip_html(descr_html) or summary

    deadline = _first(md, "deadlineDate", "")[:10] or None
    start    = _first(md, "startDate", "")[:10] or None

    types_action = _first(md, "typesOfAction", "")
    framework    = str(_first(md, "frameworkProgramme", ""))
    keywords     = md.get("keywords", []) or []
    if not isinstance(keywords, list):
        keywords = [keywords]

    # Stato: attivo solo se deadline non passata (doppio check oltre allo status)
    stato = "attivo"
    if deadline and deadline < date.today().isoformat():
        stato = "scaduto"

    bid = f"EU-FT-{reference[:60]}"
    return {
        "id":                 bid,
        "fonte":              "EU-FT",
        "tipo":               _infer_tipo(types_action, framework),
        "titolo":             title[:500],
        "descrizione":        (descr[:2000]) if descr else None,
        "ente_nome":          "European Commission",
        "ente_paese":         "EU",
        "regione":            None,
        "importo_min":        None,
        "importo_max":        None,
        "importo_stimato":    None,
        "valuta":             "EUR",
        "data_pubblicazione": start,
        "data_scadenza":      deadline,
        "stato":              stato,
        "url_originale":      r.get("url") or _first(md, "url"),
        "url_pdf":             None,
        "cpv_codes":          [],
        "settori":            _infer_settori(keywords, title),
        "destinatari":        ["universita", "enti_ricerca", "aziende"],
        "_raw":               {"reference": reference,
                                "callIdentifier": _first(md, "callIdentifier"),
                                "status": status},
    }


def fetch_page(page_number: int, page_size: int = 100,
               types: list = ("1", "2"),
               statuses: list = ("31094501", "31094502")) -> dict:
    """Una pagina dell'API SEDIA con filtro server-side per tipo+status."""
    params = {
        "apiKey":     API_KEY,
        "text":       "***",
        "pageSize":   page_size,
        "pageNumber": page_number,
        "sort":       "sortDate-desc",
    }
    body = {
        "query": {
            "bool": {
                "must": [
                    {"terms": {"type": list(types)}},
                    {"terms": {"status": list(statuses)}},
                    # filter SUPPLETIVO: campo nested
                    {"terms": {"metadata.status": list(statuses)}},
                ]
            }
        }
    }
    r = requests.post(API_URL, params=params, json=body, headers=HDR, timeout=60)
    r.raise_for_status()
    return r.json()


def scrape_eu_ft(max_records: int = 1000, page_size: int = 100,
                 verbose: bool = True) -> int:
    init_db()
    total_imported = 0
    skipped = 0
    page = 1

    while total_imported + skipped < max_records:
        try:
            j = fetch_page(page, page_size=page_size)
        except requests.HTTPError as e:
            print(f"[EU-FT] HTTP error pag.{page}: {e}", flush=True)
            break

        results = j.get("results", []) or []
        total_avail = j.get("totalResults", 0)
        if not results:
            break

        for item in results:
            bando = _parse_result(item)
            if not bando:
                skipped += 1
                continue
            try:
                upsert_bando(bando)
                total_imported += 1
            except Exception as e:
                if verbose and skipped < 3:
                    print(f"[EU-FT] WARN insert: {e}", flush=True)
                skipped += 1

        if verbose:
            print(f"[EU-FT] pag.{page}: {len(results)} recv -> "
                  f"importati {total_imported}, skip {skipped} "
                  f"(totale disponibile: {total_avail})", flush=True)

        if len(results) < page_size:
            break
        page += 1
        time.sleep(0.4)

    print(f"[EU-FT] Completato: {total_imported} bandi importati, "
          f"{skipped} skip", flush=True)
    return total_imported


def main():
    p = argparse.ArgumentParser(description="EU Funding & Tenders scraper")
    p.add_argument("--max", type=int, default=1000,
                   help="Max record da fetchare totali")
    p.add_argument("--page-size", type=int, default=100,
                   help="Record per pagina API")
    args = p.parse_args()
    scrape_eu_ft(max_records=args.max, page_size=args.page_size)


if __name__ == "__main__":
    main()
