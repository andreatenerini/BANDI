"""
Scraper OpenAIRE/CORDIS -- organizzazioni e progetti EU con partecipanti italiani.
API: https://api.openaire.eu/graph/v1/
Nessuna autenticazione richiesta.
Fonte dati: OpenAIRE aggrega CORDIS (H2020, Horizon Europe, ERC, MSCA, ...).
"""
import json
import time
import requests
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.db import init_db
from entity.entity_db import upsert_entita, upsert_segnale

OPENAIRE_BASE = "https://api.openaire.eu/graph/v1"
HEADERS = {"Accept": "application/json", "User-Agent": "BANDI-scraper/1.0"}


def _get(endpoint: str, params: dict) -> dict | None:
    try:
        r = requests.get(f"{OPENAIRE_BASE}/{endpoint}",
                         params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"[CORDIS] Errore {endpoint}: {e}")
        return None


def _tipo_from_org(org: dict) -> str:
    name = (org.get("legalName") or "").lower()
    if any(k in name for k in ["universit", "politecnic", "scuola superiore"]):
        return "universita"
    if any(k in name for k in ["istituto", "cnr", "infn", "inaf", "fondazione", "centro"]):
        return "ente_ricerca"
    return "azienda"


def scrape_cordis_orgs(
    country_code: str = "IT",
    max_orgs: int = 500,
    verbose: bool = True,
) -> int:
    """
    Scarica organizzazioni italiane da OpenAIRE (proxy CORDIS).
    13.400+ organizzazioni IT note a OpenAIRE.

    Args:
        country_code: codice ISO paese (default IT)
        max_orgs:     limite entita da importare
        verbose:      stampa progressi

    Returns:
        Numero di entita salvate
    """
    total = 0
    page  = 1
    page_size = min(50, max_orgs)

    while total < max_orgs:
        data = _get("organizations", {
            "countryCode": country_code,
            "page":        page,
            "pageSize":    page_size,
        })
        if not data:
            break

        results = data.get("results", [])
        if not results:
            break

        for org in results:
            if total >= max_orgs:
                break

            nome = org.get("legalName") or org.get("legalShortName", "")
            if not nome:
                continue

            tipo = _tipo_from_org(org)

            # PIC code (EU participant identifier)
            pids = org.get("pids") or []
            pic  = next((p["value"] for p in pids if p.get("scheme") == "PIC"), None)

            eid = upsert_entita({
                "id":       f"OA-ORG-{org['id'].split('::')[-1][:16]}",
                "tipo":     tipo,
                "nome":     nome,
                "paese":    country_code,
                "sito_web": org.get("websiteUrl"),
            })

            # Segnale: codice PIC (identificatore EU ufficiale)
            if pic:
                upsert_segnale(eid, "eu_pic_code", pic,
                               peso=2.0, fonte="OpenAIRE/CORDIS")

            # Segnale: OpenAIRE ID
            upsert_segnale(eid, "openaire_id", org["id"],
                           peso=1.0, fonte="OpenAIRE")

            total += 1

        if verbose:
            print(f"[CORDIS] {total} organizzazioni importate (pag.{page})")

        # Controlla se ci sono altre pagine
        num_found = data.get("header", {}).get("numFound", 0)
        if total >= num_found:
            break

        page += 1
        time.sleep(0.2)

    print(f"[CORDIS] Completato: {total} organizzazioni IT salvate")
    return total


def scrape_cordis_projects(
    funding_stream: str = "HE",
    country_code: str = "IT",
    max_projects: int = 200,
    verbose: bool = True,
) -> int:
    """
    Scarica progetti EU (Horizon Europe / H2020) e ne salva le keyword come
    segnali sulle organizzazioni gia' presenti nel DB.

    Args:
        funding_stream: "HE" = Horizon Europe | "H2020" | "FP7"
        country_code:   filtro paese coordinatore
        max_projects:   limite progetti
        verbose:        stampa progressi

    Returns:
        Numero di segnali aggiornati
    """
    total_signals = 0
    page = 1

    while total_signals // 5 < max_projects:
        data = _get("projects", {
            "fundingStreamId": funding_stream,
            "page":            page,
            "pageSize":        50,
        })
        if not data:
            break

        results = data.get("results", [])
        if not results:
            break

        for proj in results:
            keywords = proj.get("keywords") or []
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split(",") if k.strip()]

            proj_id    = proj.get("id", "")
            grant_code = proj.get("code", "")

            # Cerca l'organizzazione nel DB per nome (se coordinatore noto)
            rel_org = proj.get("relOrganizationName", "")
            if rel_org:
                from scraper.db import get_conn
                conn = get_conn()
                rows = conn.execute(
                    "SELECT id FROM entita WHERE nome LIKE ?",
                    (f"%{rel_org[:30]}%",)
                ).fetchall()
                conn.close()

                for row in rows:
                    eid = row["id"]
                    upsert_segnale(eid, "eu_project_keyword",
                                   f"{funding_stream}:{grant_code}",
                                   peso=1.5, fonte="OpenAIRE",
                                   raw={"keywords": keywords[:5]})
                    total_signals += 1

        if verbose and page % 5 == 0:
            print(f"[CORDIS] Pag.{page}: {total_signals} segnali progetti")

        num_found = data.get("header", {}).get("numFound", 0)
        if page * 50 >= min(num_found, max_projects * 5):
            break

        page += 1
        time.sleep(0.3)

    print(f"[CORDIS] Progetti: {total_signals} segnali aggiornati")
    return total_signals


def scrape_cordis(
    max_projects: int = 300,
    verbose: bool = True,
) -> int:
    """
    Entry point principale: scarica organizzazioni IT + segnali progetti.
    """
    n_orgs = scrape_cordis_orgs(max_orgs=max_projects, verbose=verbose)
    n_sig  = scrape_cordis_projects(max_projects=max_projects // 2, verbose=verbose)
    return n_orgs


if __name__ == "__main__":
    init_db()
    scrape_cordis(max_projects=100)
