"""
Scraper OpenAlex — ricercatori e istituzioni italiane.
API pubblica, nessuna chiave necessaria (polite pool con email).
Docs: https://docs.openalex.org/
"""
import json
import time
import requests
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.db import init_db
from entity.entity_db import upsert_entita, upsert_segnale, upsert_pubblicazione

BASE = "https://api.openalex.org"
EMAIL = "atenerini@idea-re.eu"   # polite pool: risposta più veloce
HEADERS = {"User-Agent": f"BANDI-scraper/1.0 (mailto:{EMAIL})"}


def _get(endpoint: str, params: dict) -> dict | None:
    params["mailto"] = EMAIL
    try:
        r = requests.get(f"{BASE}/{endpoint}", params=params,
                         headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"[OpenAlex] Errore {endpoint}: {e}")
        return None


def _parse_author(item: dict) -> dict:
    """Normalizza un autore OpenAlex nel formato entita."""
    oa_id = item.get("id", "").split("/")[-1]  # A123456789
    name  = item.get("display_name", "")

    # Istituzione principale
    aff = (item.get("affiliations") or [{}])[0]
    inst = aff.get("institution") or {}

    # Keywords dai concetti più rilevanti
    concepts = item.get("x_concepts") or item.get("topics") or []
    kws = [c.get("display_name", "") for c in concepts[:10]
           if c.get("score", 0) > 0.3]

    return {
        "id":           f"OA-{oa_id}",
        "tipo":         "ricercatore",
        "nome":         name,
        "piva":         None,
        "sede_citta":   inst.get("geo", {}).get("city"),
        "sede_regione": inst.get("geo", {}).get("region"),
        "paese":        inst.get("country_code", "IT"),
        "sito_web":     item.get("orcid"),
        "_keywords":    kws,
        "_oa_id":       oa_id,
        "_institution": inst.get("display_name"),
        "_works_count": item.get("works_count", 0),
        "_cited_by":    item.get("cited_by_count", 0),
    }


def scrape_openalex_authors(
    institution_ror: str = None,
    country_code: str = "IT",
    min_works: int = 5,
    max_authors: int = 500,
    verbose: bool = True,
) -> int:
    """
    Scarica ricercatori italiani da OpenAlex e li salva nel DB.

    Args:
        institution_ror: ROR id istituzione (es. "03yxnpp24" per Univ. Bologna)
                         Se None → prende tutti gli autori italiani
        country_code:    filtro paese (default IT)
        min_works:       minimo opere pubblicate
        max_authors:     limite entità da importare
        verbose:         stampa progressi

    Returns:
        Numero di ricercatori importati
    """
    filters = [f"last_known_institutions.country_code:{country_code}"]
    if institution_ror:
        filters.append(f"last_known_institutions.ror:{institution_ror}")
    if min_works:
        filters.append(f"works_count:>{min_works}")

    params = {
        "filter":      ",".join(filters),
        "sort":        "cited_by_count:desc",
        "per-page":    200,
        "cursor":      "*",
        "select":      "id,display_name,affiliations,x_concepts,topics,"
                       "works_count,cited_by_count,orcid",
    }

    total = 0
    while total < max_authors:
        data = _get("authors", params)
        if not data:
            break

        items = data.get("results", [])
        if not items:
            break

        for item in items:
            if total >= max_authors:
                break

            parsed = _parse_author(item)
            eid = upsert_entita(parsed)

            # Segnali: keyword concettuali
            for kw in parsed.get("_keywords", []):
                upsert_segnale(eid, "openalex_concept", kw,
                               peso=0.8, fonte="OpenAlex",
                               data_rilevazione=None)

            # Segnale: istituzione
            if parsed.get("_institution"):
                upsert_segnale(eid, "istituzione",
                               parsed["_institution"],
                               peso=1.0, fonte="OpenAlex")

            # Segnali metrici: produttivita + impatto del ricercatore
            wc = parsed.get("_works_count") or 0
            cb = parsed.get("_cited_by") or 0
            if wc > 0:
                # peso log-scalato: 10 works = peso 1, 100 = 2, 1000 = 3
                from math import log10
                upsert_segnale(eid, "oa_works_count", str(wc),
                               peso=round(log10(max(wc, 1)), 2),
                               fonte="OpenAlex")
            if cb > 0:
                from math import log10
                upsert_segnale(eid, "oa_citations", str(cb),
                               peso=round(log10(max(cb, 1)), 2),
                               fonte="OpenAlex")

            total += 1

        if verbose:
            print(f"[OpenAlex] {total} ricercatori importati...")

        next_cursor = data.get("meta", {}).get("next_cursor")
        if not next_cursor:
            break
        params["cursor"] = next_cursor
        time.sleep(0.2)

    print(f"[OpenAlex] Completato: {total} ricercatori salvati")
    return total


def scrape_openalex_works(
    entita_id: str,
    oa_author_id: str,
    max_works: int = 50,
) -> int:
    """
    Scarica le pubblicazioni di un ricercatore e le salva nel DB.
    Da chiamare dopo scrape_openalex_authors per arricchire i profili.
    """
    params = {
        "filter":   f"author.id:{oa_author_id}",
        "sort":     "cited_by_count:desc",
        "per-page": min(max_works, 200),
        "select":   "id,title,publication_year,concepts,doi",
    }

    data = _get("works", params)
    if not data:
        return 0

    count = 0
    for w in data.get("results", []):
        wid = w.get("id", "").split("/")[-1]
        concetti = [c.get("display_name") for c in (w.get("concepts") or [])[:8]]
        upsert_pubblicazione({
            "id":          f"OA-W-{wid}",
            "entita_id":   entita_id,
            "titolo":      w.get("title", ""),
            "anno":        w.get("publication_year"),
            "concetti":    concetti,
            "doi":         w.get("doi"),
            "fonte":       "OpenAlex",
            "openalex_id": w.get("id"),
        })
        count += 1

    return count


def scrape_openalex_institutions(
    country_code: str = "IT",
    max_inst: int = 200,
    verbose: bool = True,
) -> int:
    """
    Scarica istituzioni di ricerca italiane (università, enti).
    """
    params = {
        "filter":   f"country_code:{country_code}",
        "sort":     "works_count:desc",
        "per-page": 200,
        "select":   "id,display_name,country_code,geo,ror,type,works_count,"
                    "cited_by_count,topics,summary_stats,homepage_url",
    }

    data = _get("institutions", params)
    if not data:
        return 0

    total = 0
    for inst in (data.get("results") or [])[:max_inst]:
        iid = inst.get("id", "").split("/")[-1]
        tipo_raw = inst.get("type", "education")
        tipo = "universita" if tipo_raw == "education" else "ente_ricerca"
        geo = inst.get("geo") or {}
        eid = upsert_entita({
            "id":           f"OA-INST-{iid}",
            "tipo":         tipo,
            "nome":         inst.get("display_name", ""),
            "paese":        inst.get("country_code", "IT"),
            "sede_citta":   geo.get("city"),
            "sede_regione": geo.get("region"),
            "sito_web":     inst.get("homepage_url"),
        })
        upsert_segnale(eid, "openalex_ror",
                       inst.get("ror") or iid,
                       peso=1.0, fonte="OpenAlex")

        # Segnali tematici dell'istituzione (campo "topics" nella v2 dell'API)
        concepts = inst.get("topics") or inst.get("x_concepts") or []
        for c in concepts[:10]:
            if c.get("count", c.get("score", 1)) > 0:
                upsert_segnale(eid, "openalex_concept",
                               c.get("display_name", ""),
                               peso=0.8, fonte="OpenAlex")

        # Segnali metrici (peso istituzione)
        from math import log10
        wc = inst.get("works_count") or 0
        cb = inst.get("cited_by_count") or 0
        if wc > 0:
            upsert_segnale(eid, "oa_works_count", str(wc),
                           peso=round(log10(max(wc, 1)), 2),
                           fonte="OpenAlex")
        if cb > 0:
            upsert_segnale(eid, "oa_citations", str(cb),
                           peso=round(log10(max(cb, 1)), 2),
                           fonte="OpenAlex")
        # h-index / i10-index dall'aggregato summary_stats
        ss = inst.get("summary_stats") or {}
        if ss.get("h_index"):
            upsert_segnale(eid, "oa_h_index", str(ss["h_index"]),
                           peso=float(min(ss["h_index"] / 50, 5.0)),
                           fonte="OpenAlex")
        total += 1

    if verbose:
        print(f"[OpenAlex] {total} istituzioni salvate")
    return total


if __name__ == "__main__":
    init_db()
    scrape_openalex_institutions()
    scrape_openalex_authors(max_authors=200)
