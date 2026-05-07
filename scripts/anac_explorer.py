"""
Esploratore ANAC catalog. Scarica catalog.jsonld UNA volta sola e ne fa il
dump strutturato in data/raw/anac/catalog_<date>.json + un riepilogo CSV.

Pattern: scaricare il catalog 2.8 MB richiama un endpoint pubblico, ma il
WAF puo' bloccare se la chiamata e' ripetuta o associata a download grossi.
Quindi: una sola chiamata, salvataggio locale, esplorazioni successive
sul file salvato.

Uso:
  python scripts/anac_explorer.py --fetch                # scarica e salva
  python scripts/anac_explorer.py                        # legge il file locale
  python scripts/anac_explorer.py --search partecipanti  # filtra per keyword
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
RAW_DIR = ROOT / "data" / "raw" / "anac"
RAW_DIR.mkdir(parents=True, exist_ok=True)

CATALOG_URL = "https://dati.anticorruzione.it/opendata/catalog.jsonld"
HDR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/ld+json,application/json",
}

DCT_TITLE       = "http://purl.org/dc/terms/title"
DCT_DESCR       = "http://purl.org/dc/terms/description"
DCT_FORMAT      = "http://purl.org/dc/terms/format"
DCT_MODIFIED    = "http://purl.org/dc/terms/modified"
DCT_ISSUED      = "http://purl.org/dc/terms/issued"
DCAT_DIST       = "http://www.w3.org/ns/dcat#distribution"
DCAT_URL        = "http://www.w3.org/ns/dcat#accessURL"


def _val(node: dict, key: str, lang: str | None = None) -> str:
    """Estrae il primo valore @value, opzionalmente filtrato per lingua."""
    items = node.get(key, [])
    if not isinstance(items, list):
        items = [items]
    for it in items:
        if isinstance(it, dict):
            if lang and it.get("@language") not in (lang, None):
                continue
            v = it.get("@value")
            if v:
                return v
    return ""


def fetch_catalog(out_path: Path) -> int:
    """Scarica il catalog DCAT e lo salva su disco. Ritorna len bytes."""
    print(f"[Explorer] GET {CATALOG_URL}")
    r = requests.get(CATALOG_URL, headers=HDR, timeout=60)
    if r.status_code != 200 or "html" in r.headers.get("Content-Type", ""):
        snippet = r.content[:200]
        print(f"[Explorer] ERR: status={r.status_code}, "
              f"content-type={r.headers.get('Content-Type')}, "
              f"snippet={snippet!r}")
        sys.exit(1)
    out_path.write_bytes(r.content)
    print(f"[Explorer]   -> {out_path} ({len(r.content) / 1024:.1f} KB)")
    return len(r.content)


def find_latest_catalog() -> Path | None:
    files = sorted(RAW_DIR.glob("catalog_*.json"), reverse=True)
    return files[0] if files else None


def is_dataset(node: dict) -> bool:
    types = node.get("@type", [])
    if not isinstance(types, list):
        types = [types]
    return "http://www.w3.org/ns/dcat#Dataset" in types


def is_distribution(node: dict) -> bool:
    types = node.get("@type", [])
    if not isinstance(types, list):
        types = [types]
    return "http://www.w3.org/ns/dcat#Distribution" in types


def explore(catalog_path: Path, search: str | None = None,
            csv_out: Path | None = None) -> None:
    """Stampa un sommario dei dataset; se search e' dato, filtra per match."""
    nodes = json.loads(catalog_path.read_text(encoding="utf-8"))
    by_id = {n.get("@id"): n for n in nodes if n.get("@id")}

    datasets = [n for n in nodes if is_dataset(n)]
    distributions = [n for n in nodes if is_distribution(n)]
    print(f"[Explorer] Catalog: {len(nodes)} nodi totali")
    print(f"           Dataset: {len(datasets)}")
    print(f"           Distribution: {len(distributions)}")
    print()

    rows = []
    for ds in datasets:
        title = _val(ds, DCT_TITLE)
        descr = _val(ds, DCT_DESCR, lang="it") or _val(ds, DCT_DESCR)
        modified = _val(ds, DCT_MODIFIED)
        n_dist = 0
        formats = set()
        for d in ds.get(DCAT_DIST, []):
            ref = d.get("@id") if isinstance(d, dict) else d
            dist_node = by_id.get(ref)
            if dist_node:
                n_dist += 1
                fmt_items = dist_node.get(DCT_FORMAT, [])
                if not isinstance(fmt_items, list):
                    fmt_items = [fmt_items]
                for fmt in fmt_items:
                    fmt_id = fmt.get("@id") if isinstance(fmt, dict) else fmt
                    if fmt_id:
                        formats.add(fmt_id.split("/")[-1])

        if search and search.lower() not in (title + " " + descr).lower():
            continue

        rows.append({
            "title":     title,
            "n_dist":    n_dist,
            "formats":   ", ".join(sorted(formats)),
            "modified":  modified[:10],
            "id":        ds.get("@id"),
            "descr":     descr[:300],
        })

    # Ordina per modificato (piu recenti in cima)
    rows.sort(key=lambda r: r["modified"], reverse=True)

    print(f"=== Dataset {'(filtro: ' + search + ')' if search else 'tutti'}: "
          f"{len(rows)} match ===")
    print()
    for r in rows[:50]:
        print(f"[{r['modified']}] {r['title']}")
        print(f"   distribuzioni: {r['n_dist']} ({r['formats']})")
        if r["descr"]:
            print(f"   descr: {r['descr'][:100]}...")
        print(f"   id: {r['id']}")
        print()

    if len(rows) > 50:
        print(f"... +{len(rows) - 50} righe non mostrate")

    if csv_out:
        with open(csv_out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["title", "n_dist", "formats",
                               "modified", "id", "descr"]
            )
            w.writeheader()
            w.writerows(rows)
        print(f"[Explorer] Scritto CSV: {csv_out}")


def main():
    p = argparse.ArgumentParser(description="ANAC catalog explorer")
    p.add_argument("--fetch", action="store_true",
                   help="Scarica il catalog (UNA volta, attenzione al WAF)")
    p.add_argument("--search", type=str, default=None,
                   help="Filtra dataset per keyword (case-insensitive)")
    p.add_argument("--csv", action="store_true",
                   help="Scrive anche un CSV in data/exports/anac_catalog.csv")
    args = p.parse_args()

    if args.fetch:
        out = RAW_DIR / f"catalog_{date.today().isoformat()}.json"
        fetch_catalog(out)
        catalog_path = out
    else:
        catalog_path = find_latest_catalog()
        if not catalog_path:
            print("[Explorer] Nessun catalog locale trovato. "
                  "Lancia con --fetch.")
            sys.exit(1)
        print(f"[Explorer] Uso catalog locale: {catalog_path.name} "
              f"({catalog_path.stat().st_size / 1024:.1f} KB)")

    csv_out = None
    if args.csv:
        csv_out = ROOT / "data" / "exports" / "anac_catalog.csv"
        csv_out.parent.mkdir(parents=True, exist_ok=True)

    explore(catalog_path, search=args.search, csv_out=csv_out)


if __name__ == "__main__":
    main()
