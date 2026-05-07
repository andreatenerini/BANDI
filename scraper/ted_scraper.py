"""
Scraper TED — Tenders Electronic Daily
API: POST https://api.ted.europa.eu/v3/notices/search
Nessuna autenticazione richiesta.
"""
import json
import time
import requests
from datetime import date, timedelta
from .config import TED_SEARCH_URL, TED_FIELDS, TED_PAGE_SIZE, TIMEOUT
from .db import upsert_bando, init_db

# Form-type validi per opportunita' aperte (escludono esiti gia' aggiudicati
# e modifiche contrattuali). Verificato su dati reali del DB:
#   competition  -> bando di gara aperto
#   planning     -> avviso preliminare (annuncio opportunita' futura)
#   consultation -> consultazione di mercato preliminare
# Esclusi: result (esito), cont-modif (modifica contratto)
TED_VALID_FORM_TYPES = {"competition", "planning", "consultation"}

# ── CPV → tipo bando ──────────────────────────────────────────────────────────
CPV_TIPO = {
    "73": "ricerca_sviluppo",
    "72": "servizi_it",
    "71": "servizi_professionali",
    "80": "formazione",
    "85": "servizi_sanitari",
    "90": "servizi_ambientali",
    "45": "lavori",
    "33": "dispositivi_medici",
    "48": "software",
}

def _cpv_to_tipo(cpv_codes: list) -> str:
    for cpv in cpv_codes:
        prefix = str(cpv)[:2]
        if prefix in CPV_TIPO:
            return CPV_TIPO[prefix]
    return "appalto_servizi"

def _cpv_to_settori(cpv_codes: list) -> list:
    settori = set()
    mapping = {
        "73": "ricerca", "72": "tecnologia", "71": "ingegneria",
        "80": "formazione", "85": "sanità", "90": "ambiente",
        "45": "costruzioni", "33": "medicale", "48": "software",
    }
    for cpv in cpv_codes:
        p = str(cpv)[:2]
        if p in mapping:
            settori.add(mapping[p])
    return list(settori)

def _parse_notice(n: dict) -> dict | None:
    """Normalizza un avviso TED nel formato comune del DB.
    Restituisce None se il form-type non e' un'opportunita' valida
    (esiti gia' aggiudicati, modifiche contrattuali...)."""
    # Filtro client-side difensivo
    ft = n.get("form-type")
    if isinstance(ft, list):
        ft = ft[0] if ft else None
    if ft and str(ft) not in TED_VALID_FORM_TYPES:
        return None

    nd   = n.get("ND", "")
    bid  = f"TED-{nd}"

    # Titolo: preferisce italiano, poi inglese
    ti = n.get("TI") or n.get("notice-title") or {}
    titolo = ti.get("ita") or ti.get("eng") or nd

    # Ente appaltante
    buyer = n.get("organisation-name-buyer") or {}
    if isinstance(buyer, dict):
        ente = (buyer.get("ita") or buyer.get("eng") or [None])
        ente = ente[0] if isinstance(ente, list) else ente
    else:
        ente = str(buyer)

    # Importo
    importo_raw = n.get("estimated-value-lot")
    importo = None
    if importo_raw:
        vals = importo_raw if isinstance(importo_raw, list) else [importo_raw]
        try:
            importo = max(float(v) for v in vals if v)
        except (ValueError, TypeError):
            pass

    # Scadenza
    deadline_raw = n.get("deadline-date-lot")
    scadenza = None
    if deadline_raw:
        vals = deadline_raw if isinstance(deadline_raw, list) else [deadline_raw]
        scadenza = vals[0] if vals else None
        if scadenza:
            scadenza = str(scadenza)[:10]

    # CPV
    cpvs = n.get("classification-cpv") or []
    if isinstance(cpvs, str):
        cpvs = [cpvs]

    # Descrizione
    desc_raw = n.get("description-lot") or {}
    if isinstance(desc_raw, dict):
        desc = desc_raw.get("ita") or desc_raw.get("eng") or ""
        if isinstance(desc, list):
            desc = " ".join(desc)
    else:
        desc = str(desc_raw)

    # Links
    links = n.get("links") or {}
    url_html = (links.get("html") or {}).get("ITA") or (links.get("html") or {}).get("ENG") or ""
    url_pdf  = (links.get("pdf") or {}).get("ITA") or (links.get("pdf") or {}).get("ENG") or ""

    # Stato
    stato = "attivo"
    if scadenza:
        try:
            if scadenza < date.today().isoformat():
                stato = "scaduto"
        except Exception:
            pass

    # Destinatari inferiti da tipo
    tipo = _cpv_to_tipo(cpvs)
    dest_map = {
        "ricerca_sviluppo": ["universita", "centri_ricerca", "aziende"],
        "formazione":       ["aziende", "enti_formazione", "universita"],
        "servizi_it":       ["aziende", "software_house"],
        "servizi_sanitari": ["aziende", "enti_sanitari"],
        "appalto_lavori":   ["aziende"],
        "appalto_servizi":  ["aziende", "pa"],
    }
    destinatari = dest_map.get(tipo, ["aziende"])

    return {
        "id":                 bid,
        "fonte":              "TED",
        "tipo":               tipo,
        "titolo":             titolo,
        "descrizione":        desc[:2000] if desc else None,
        "ente_nome":          ente,
        "ente_paese":         (n.get("buyer-country") or ["IT"])[0] if isinstance(n.get("buyer-country"), list) else n.get("buyer-country", "IT"),
        "importo_min":        None,
        "importo_max":        None,
        "importo_stimato":    importo,
        "valuta":             "EUR",
        "data_pubblicazione": str(n.get("dispatch-date", ""))[:10] or None,
        "data_scadenza":      scadenza,
        "stato":              stato,
        "url_originale":      url_html,
        "url_pdf":            url_pdf,
        "cpv_codes":          [str(c) for c in cpvs],
        "settori":            _cpv_to_settori(cpvs),
        "destinatari":        destinatari,
        "_form_type":         ft,
        "_raw":               n,
    }


def scrape_ted(
    query: str = "buyer-country=ITA",
    days_back: int = 90,
    max_pages: int = 20,
    verbose: bool = True,
) -> int:
    """
    Scarica bandi TED e li salva nel DB.

    Args:
        query:      query TED expert search (es. "buyer-country=ITA AND classification-cpv=73000000")
        days_back:  quanti giorni indietro cercare
        max_pages:  limite pagine (50 record/pag)
        verbose:    stampa progressi

    Returns:
        Numero di bandi inseriti/aggiornati
    """
    since = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    # Filtro server-side per escludere esiti gia' aggiudicati e modifiche
    form_filter = " OR ".join(
        f"form-type={ft}" for ft in sorted(TED_VALID_FORM_TYPES)
    )
    full_query = f"({query}) AND dispatch-date>={since} AND ({form_filter})"

    body = {
        "query":           full_query,
        "fields":          TED_FIELDS,
        "limit":           TED_PAGE_SIZE,
        "scope":           "ALL",
        "checkQuerySyntax": False,
        "paginationMode":  "ITERATION",
    }

    total = 0
    page  = 0

    while page < max_pages:
        try:
            r = requests.post(
                TED_SEARCH_URL,
                json=body,
                timeout=TIMEOUT,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            r.raise_for_status()
        except requests.HTTPError as e:
            print(f"[TED] Errore HTTP {e.response.status_code}: {e.response.text[:300]}")
            break
        except requests.RequestException as e:
            print(f"[TED] Errore connessione: {e}")
            break

        data = r.json()
        notices = data.get("notices", [])

        if not notices:
            break

        for n in notices:
            bando = _parse_notice(n)
            if bando is None:
                continue  # form-type filtrato
            upsert_bando(bando)
            total += 1

        if verbose:
            print(f"[TED] pag.{page+1} -> {len(notices)} avvisi (tot. {total})")

        # Paginazione ITERATION: il token è nell'header o nel body di risposta
        next_page = data.get("links", {}).get("next")
        if not next_page:
            break

        body["iterationNextToken"] = data.get("iterationNextToken") or ""
        if not body["iterationNextToken"]:
            break

        page += 1
        time.sleep(0.5)  # rispetta i rate limit

    print(f"[TED] Completato: {total} bandi salvati nel DB")
    return total


# Preset query utili ──────────────────────────────────────────────────────────
# Mappa CPV → nome query: i CPV sono prefissi a 2 cifre della classificazione UE.
# Vedi https://simap.ted.europa.eu/cpv per l'elenco completo.
PRESET_QUERIES = {
    "it_servizi":      "buyer-country=ITA",
    "it_ricerca":      "buyer-country=ITA AND classification-cpv=73000000",
    "it_it_services":  "buyer-country=ITA AND classification-cpv=72000000",
    "it_consulenza":   "buyer-country=ITA AND classification-cpv=71000000",
    "it_costruzioni":  "buyer-country=ITA AND classification-cpv=45000000",
    "it_sanita":       "buyer-country=ITA AND classification-cpv=85000000",
    "it_ambiente":     "buyer-country=ITA AND classification-cpv=90000000",
    "it_formazione":   "buyer-country=ITA AND classification-cpv=80000000",
    "eu_ricerca":      "classification-cpv=73000000",
    "eu_formazione":   "classification-cpv=80000000",
}

if __name__ == "__main__":
    init_db()
    for name, q in PRESET_QUERIES.items():
        print(f"\n-- Query: {name} --")
        scrape_ted(query=q, days_back=365, max_pages=100)
