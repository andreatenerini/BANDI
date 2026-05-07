"""
Scraper ANAC v2 — JSON OCDS streaming dal portale ristrutturato.

Sostituisce il vecchio anac_scraper.py (che usava CSV bulk con URL ora 404).

Pipeline:
  1. Scarica il catalog DCAT (catalog.jsonld)
  2. Identifica il dataset OCDS dell'anno target e la distribuzione mensile
  3. Scarica il JSON in streaming (~1 GB / mese)
  4. Parsa con ijson le releases una alla volta (memory-efficient)
  5. Per ciascuna release:
     - se ha tender attivo -> upsert in 'bandi'
     - se ha awards aggiudicati -> upsert entita aziende + contratti_vinti
  6. Cancella il file grezzo (no spazio extra)

Uso:
    python -m scraper.anac_v2                  # mese piu' recente, default
    python -m scraper.anac_v2 --year 2024 --month 8
    python -m scraper.anac_v2 --keep-raw       # conserva il JSON in data/raw/
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import ijson
import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scraper.db import init_db, upsert_bando  # noqa: E402
from entity.entity_db import (  # noqa: E402
    upsert_entita, upsert_segnale, upsert_contratto_vinto,
)

CATALOG_URL = "https://dati.anticorruzione.it/opendata/catalog.jsonld"
HDR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,application/ld+json",
}

DCT_TITLE  = "http://purl.org/dc/terms/title"
DCT_FORMAT = "http://purl.org/dc/terms/format"
DCAT_DIST  = "http://www.w3.org/ns/dcat#distribution"
DCAT_URL   = "http://www.w3.org/ns/dcat#accessURL"


# ─────────────────────────────────────────────────────────────────────────────
# CATALOG DISCOVERY
# ─────────────────────────────────────────────────────────────────────────────

def _title_of(node: dict) -> str:
    titles = node.get(DCT_TITLE, [])
    if not isinstance(titles, list):
        titles = [titles]
    for t in titles:
        if isinstance(t, dict):
            v = t.get("@value")
            if v:
                return v
    return ""


def _is_dataset(node: dict) -> bool:
    types = node.get("@type", [])
    if not isinstance(types, list):
        types = [types]
    return "http://www.w3.org/ns/dcat#Dataset" in types


def _list_distributions(node: dict, by_id: dict) -> list[dict]:
    out = []
    for d in node.get(DCAT_DIST, []):
        ref = d.get("@id") if isinstance(d, dict) else d
        n = by_id.get(ref)
        if n:
            out.append(n)
    return out


def fetch_catalog() -> tuple[list, dict]:
    """Ritorna (catalog_nodes, by_id_map)."""
    print(f"[ANACv2] Fetching catalog: {CATALOG_URL}")
    r = requests.get(CATALOG_URL, headers=HDR, timeout=60)
    r.raise_for_status()
    nodes = r.json()
    by_id = {n.get("@id"): n for n in nodes if n.get("@id")}
    print(f"[ANACv2]   {len(nodes)} nodi, {len(by_id)} con @id")
    return nodes, by_id


def find_ocds_distribution(
    nodes: list, by_id: dict, year: int, month: int
) -> tuple[str, str] | None:
    """
    Cerca la distribuzione JSON del mese richiesto.
    Ritorna (download_url, dist_title) o None.
    """
    target_dataset = f"OCDS appalti ordinari anno {year}"
    for ds in nodes:
        if not _is_dataset(ds):
            continue
        if _title_of(ds) != target_dataset:
            continue
        for dist in _list_distributions(ds, by_id):
            title = _title_of(dist)
            # i title sono tipo "ocds_appalti_ordinari_2024_08"
            if title.endswith(f"_{year}_{month:02d}"):
                urls = dist.get(DCAT_URL, [])
                if not isinstance(urls, list):
                    urls = [urls]
                for u in urls:
                    val = u.get("@id") if isinstance(u, dict) else u
                    if val and val.endswith(".json"):
                        return val, title
    return None


def find_latest_available(nodes: list, by_id: dict) -> tuple[int, int]:
    """Scopre l'anno+mese piu' recente disponibile come distribuzione JSON."""
    best = (0, 0)
    for ds in nodes:
        if not _is_dataset(ds):
            continue
        title = _title_of(ds)
        if not title.startswith("OCDS appalti ordinari anno "):
            continue
        try:
            year = int(title.split()[-1])
        except ValueError:
            continue
        for dist in _list_distributions(ds, by_id):
            t = _title_of(dist)
            # ocds_appalti_ordinari_YYYY_MM
            parts = t.split("_")
            if len(parts) >= 5 and parts[-1].isdigit():
                m = int(parts[-1])
                if (year, m) > best:
                    best = (year, m)
    return best


# ─────────────────────────────────────────────────────────────────────────────
# STREAMING DOWNLOAD
# ─────────────────────────────────────────────────────────────────────────────

def download_stream(url: str, out_path: Path) -> int:
    """Scarica in chunk verso file (no memoria). Ritorna bytes scaricati."""
    print(f"[ANACv2] Download streaming: {url}")
    print(f"[ANACv2]   -> {out_path}")
    r = requests.get(url, headers=HDR, stream=True, timeout=120)
    r.raise_for_status()
    total = int(r.headers.get("Content-Length", "0"))
    print(f"[ANACv2]   atteso: {total / 1e9:.2f} GB")

    written = 0
    last_pct = -1
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                written += len(chunk)
                if total:
                    pct = int(written * 100 / total)
                    if pct != last_pct and pct % 5 == 0:
                        print(f"[ANACv2]   {pct}% ({written / 1e9:.2f} GB)")
                        last_pct = pct
    print(f"[ANACv2] Download completato: {written / 1e9:.2f} GB")
    return written


# ─────────────────────────────────────────────────────────────────────────────
# PARSING + IMPORT
# ─────────────────────────────────────────────────────────────────────────────

def _is_tender_active(tender: dict) -> bool:
    status = (tender.get("status") or "").lower()
    if status not in ("active", "planning", "planned"):
        return False
    end = (tender.get("tenderPeriod") or {}).get("endDate", "")
    if end:
        try:
            end_date = datetime.fromisoformat(end.replace("Z", "+00:00")).date()
            if end_date < date.today():
                return False
        except (ValueError, TypeError):
            pass
    return True


def _parse_tender(release: dict) -> dict | None:
    tender = release.get("tender")
    if not tender:
        return None
    if not _is_tender_active(tender):
        return None

    cig = tender.get("id") or release.get("id", "")
    if not cig:
        return None

    titolo = tender.get("title", "") or ""
    desc   = tender.get("description", "") or ""

    importo = None
    val = tender.get("value") or {}
    if val.get("amount"):
        try:
            importo = float(val["amount"])
        except (TypeError, ValueError):
            pass

    end_date = (tender.get("tenderPeriod") or {}).get("endDate", "")
    scadenza = end_date[:10] if end_date else None

    buyer = release.get("buyer") or {}
    ente_nome = buyer.get("name") or ""

    # CPV dai lots o items
    cpvs = set()
    for lot in tender.get("lots", []) or []:
        items = lot.get("items", []) or []
        for it in items:
            cls = it.get("classification") or {}
            if cls.get("scheme") == "CPV" and cls.get("id"):
                cpvs.add(cls["id"])
    for it in tender.get("items", []) or []:
        cls = it.get("classification") or {}
        if cls.get("scheme") == "CPV" and cls.get("id"):
            cpvs.add(cls["id"])

    # Settore inferito dai primi 2 caratteri del CPV
    settori = set()
    cpv_to_settore = {
        "73": "ricerca", "72": "tecnologia", "71": "ingegneria",
        "80": "formazione", "85": "sanita", "90": "ambiente",
        "45": "costruzioni", "33": "medicale", "48": "software",
    }
    for c in cpvs:
        s = cpv_to_settore.get(str(c)[:2])
        if s:
            settori.add(s)

    cat = (tender.get("mainProcurementCategory") or "services").lower()
    tipo_map = {
        "services": "appalto_servizi",
        "goods":    "appalto_forniture",
        "works":    "appalto_lavori",
    }
    tipo = tipo_map.get(cat, "appalto_servizi")

    bid = f"ANAC-{cig}"
    return {
        "id":                 bid,
        "fonte":              "ANAC",
        "tipo":               tipo,
        "titolo":             titolo[:500],
        "descrizione":        desc[:2000] if desc else None,
        "ente_nome":          ente_nome[:200],
        "ente_paese":         "IT",
        "regione":            None,  # ANAC non espone regione direttamente nel tender
        "importo_min":        None,
        "importo_max":        None,
        "importo_stimato":    importo,
        "valuta":             val.get("currency", "EUR"),
        "data_pubblicazione": (release.get("date") or "")[:10] or None,
        "data_scadenza":      scadenza,
        "stato":              "attivo",
        "url_originale":      f"https://dati.anticorruzione.it/opendata/dataset/ocds-appalti-ordinari-{cig[:4]}",
        "url_pdf":             None,
        "cpv_codes":          list(cpvs),
        "settori":            list(settori),
        "destinatari":        ["aziende"],
        "_raw":               {"cig": cig, "release_id": release.get("id")},
    }


def _parse_awards(release: dict) -> list[tuple[dict, dict]]:
    """Per ogni award, ritorna (entita_dict, contratto_dict)."""
    out = []
    awards = release.get("awards") or []
    cig = (release.get("tender") or {}).get("id") or release.get("id", "")
    buyer = release.get("buyer") or {}
    ente_appaltante = buyer.get("name") or ""

    for i, award in enumerate(awards):
        if (award.get("status") or "").lower() != "active":
            continue
        suppliers = award.get("suppliers") or []
        if not suppliers:
            continue

        importo = None
        val = award.get("value") or {}
        if val.get("amount"):
            try:
                importo = float(val["amount"])
            except (TypeError, ValueError):
                pass

        date_str = award.get("date") or ""
        anno = None
        if date_str:
            try:
                anno = int(date_str[:4])
            except ValueError:
                pass

        # CPV dal primo item del primo lot/items dell'award
        cpv = None
        for it in award.get("items", []) or []:
            cls = it.get("classification") or {}
            if cls.get("scheme") == "CPV" and cls.get("id"):
                cpv = cls["id"][:8]
                break

        for j, sup in enumerate(suppliers):
            nome = (sup.get("name") or "").strip()
            piva = (sup.get("id") or "").strip()
            if not nome:
                continue

            # CIG-supplier-index per rendere unico l'ID contratto
            contract_id = f"ANAC-AWD-{cig}-{award.get('id', i)}-{j}"
            entita = {
                "tipo":  "azienda",
                "nome":  nome,
                "piva":  piva or None,
                "paese": "IT",
            }
            contratto = {
                "id":              contract_id,
                "cpv":             cpv,
                "importo":         (importo / len(suppliers)) if importo else None,
                "ente_appaltante": ente_appaltante[:200] or None,
                "anno":            anno,
                "fonte":           "ANAC",
            }
            out.append((entita, contratto))
    return out


def stream_releases(json_path: Path) -> Iterable[dict]:
    """Itera le releases del file OCDS senza caricare tutto in memoria."""
    with open(json_path, "rb") as f:
        for release in ijson.items(f, "releases.item"):
            yield release


def import_ocds_file(json_path: Path) -> dict:
    init_db()
    stats = {
        "releases":            0,
        "tender_attivi":       0,
        "tender_skipped":      0,
        "awards_processati":   0,
        "entita_create":       0,
        "contratti_create":    0,
    }
    print(f"[ANACv2] Parsing streaming: {json_path}")

    last_log = 0
    for release in stream_releases(json_path):
        stats["releases"] += 1

        # 1) Tender -> bandi
        bando = _parse_tender(release)
        if bando:
            try:
                upsert_bando(bando)
                stats["tender_attivi"] += 1
            except Exception as e:
                print(f"[ANACv2] WARN insert bando: {e}")
        else:
            stats["tender_skipped"] += 1

        # 2) Awards -> entita + contratti_vinti
        for entita, contratto in _parse_awards(release):
            try:
                eid = upsert_entita(entita)
                contratto["entita_id"] = eid
                # Segnale: CPV vinto
                if contratto.get("cpv"):
                    upsert_segnale(
                        eid, "cpv_vinto", contratto["cpv"],
                        peso=3.0, fonte="ANAC",
                        data_rilevazione=str(contratto.get("anno") or ""),
                    )
                upsert_contratto_vinto(contratto)
                stats["awards_processati"] += 1
                stats["entita_create"] += 1
                stats["contratti_create"] += 1
            except Exception as e:
                # contratti duplicati o errori upsert: skip silenziosamente
                pass

        if stats["releases"] - last_log >= 5000:
            last_log = stats["releases"]
            print(f"[ANACv2]   {stats['releases']:,} releases - "
                  f"bandi attivi: {stats['tender_attivi']}, "
                  f"contratti: {stats['contratti_create']}")

    print(f"[ANACv2] Import completato: {stats}")
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="ANAC v2 OCDS streaming scraper")
    p.add_argument("--year", type=int, default=None, help="Anno (default: piu' recente)")
    p.add_argument("--month", type=int, default=None, help="Mese 1-12 (default: piu' recente)")
    p.add_argument("--keep-raw", action="store_true",
                   help="Conserva il JSON in data/raw/anac/ dopo l'import")
    p.add_argument("--raw-file", type=str, default=None,
                   help="Salta download, usa il file locale specificato")
    args = p.parse_args()

    if args.raw_file:
        json_path = Path(args.raw_file)
        stats = import_ocds_file(json_path)
        print(f"[ANACv2] Done: {stats}")
        return

    nodes, by_id = fetch_catalog()

    if args.year is None or args.month is None:
        y, m = find_latest_available(nodes, by_id)
        if y == 0:
            print("[ANACv2] ERR: nessun dataset OCDS trovato nel catalog")
            sys.exit(1)
        year, month = args.year or y, args.month or m
        print(f"[ANACv2] Mese piu' recente disponibile: {year}/{month:02d}")
    else:
        year, month = args.year, args.month

    found = find_ocds_distribution(nodes, by_id, year, month)
    if not found:
        print(f"[ANACv2] ERR: distribuzione {year}/{month:02d} non trovata")
        sys.exit(1)
    url, title = found
    print(f"[ANACv2] Distribuzione: {title}")

    # Download
    if args.keep_raw:
        target = ROOT / "data" / "raw" / "anac"
        target.mkdir(parents=True, exist_ok=True)
        json_path = target / f"ocds_{year}_{month:02d}.json"
        download_stream(url, json_path)
        cleanup = False
    else:
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False,
            dir=str(ROOT / "data" / "raw"),
        ) as tf:
            json_path = Path(tf.name)
        (ROOT / "data" / "raw").mkdir(parents=True, exist_ok=True)
        download_stream(url, json_path)
        cleanup = True

    # Import
    try:
        stats = import_ocds_file(json_path)
    finally:
        if cleanup:
            try:
                json_path.unlink()
                print(f"[ANACv2] File temp eliminato: {json_path.name}")
            except OSError:
                pass

    print(f"[ANACv2] Done. Stats: {stats}")


if __name__ == "__main__":
    main()
