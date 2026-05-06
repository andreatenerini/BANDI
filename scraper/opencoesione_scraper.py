"""
Scraper OpenCoesione -- Fondi strutturali EU, PNRR, FESR, FSE+.
API pubblica: https://opencoesione.gov.it/it/api/
Dati aggiornati al 31/12/2025. 1.8M+ progetti, 11 temi tematici.

Uso nel sistema:
  - Bandi: programmi di finanziamento attivi per tema
  - Entita: soggetti beneficiari (vedi entity/opencoesione_beneficiari.py)
"""
import json
import time
import requests
from datetime import datetime
from pathlib import Path

from .config import DATA_RAW, HEADERS, TIMEOUT
from .db import upsert_bando, init_db

OC_BASE   = "https://opencoesione.gov.it/it/api"
OC_RAW    = DATA_RAW / "opencoesione"
OC_RAW.mkdir(parents=True, exist_ok=True)

# Temi OpenCoesione → tipo bando + settori nel DB
TEMI = {
    "ricerca-e-innovazione":  ("ricerca_nazionale",   ["ricerca", "innovazione"]),
    "reti-servizi-digitali":  ("appalto_servizi",     ["tecnologia", "digitale"]),
    "competitivita-imprese":  ("incentivo_imprese",   ["imprese", "innovazione"]),
    "energia":                ("appalto_servizi",     ["energia", "ambiente"]),
    "ambiente":               ("appalto_servizi",     ["ambiente"]),
    "cultura-e-turismo":      ("incentivo_imprese",   ["cultura", "turismo"]),
    "trasporti":              ("appalto_lavori",      ["trasporti", "infrastrutture"]),
    "occupazione":            ("formazione",          ["lavoro", "formazione"]),
    "inclusione-sociale":     ("appalto_servizi",     ["sociale", "salute"]),
    "istruzione":             ("formazione",          ["istruzione", "formazione"]),
    "capacita-amministrativa":("appalto_servizi",     ["pubblica_amministrazione"]),
}

DESTINATARI_TEMA = {
    "ricerca-e-innovazione":  ["universita", "enti_ricerca", "aziende"],
    "reti-servizi-digitali":  ["aziende", "software_house", "pa"],
    "competitivita-imprese":  ["aziende", "startup", "pmi"],
    "energia":                ["aziende", "enti_pubblici"],
    "ambiente":               ["aziende", "enti_pubblici", "comuni"],
    "cultura-e-turismo":      ["aziende", "enti_pubblici", "comuni"],
    "trasporti":              ["enti_pubblici", "aziende"],
    "occupazione":            ["aziende", "enti_formazione"],
    "inclusione-sociale":     ["enti_pubblici", "no_profit", "aziende"],
    "istruzione":             ["scuole", "universita", "enti_formazione"],
    "capacita-amministrativa":["pa", "enti_pubblici"],
}


def _get(url: str, params: dict = None) -> dict | None:
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"[OC] Errore {url[:60]}: {e}")
        return None


def _parse_programma(prog: dict, tema_slug: str) -> dict | None:
    """Normalizza un programma OpenCoesione in formato bando."""
    codice   = prog.get("codice", "")
    titolo   = prog.get("descrizione", prog.get("codice", "")).strip()
    if not titolo:
        return None

    tipo, settori = TEMI.get(tema_slug, ("incentivo_imprese", [tema_slug]))
    dest          = DESTINATARI_TEMA.get(tema_slug, ["aziende"])

    # Importo: da aggregati se disponibili
    importo = None
    fin = prog.get("oc_finanz_tot_pub_netto")
    if fin:
        try:
            importo = float(str(fin).replace(".", "").replace(",", "."))
        except ValueError:
            pass

    bid = f"OC-{codice}" if codice else f"OC-{abs(hash(titolo)) % 10**8}"

    return {
        "id":                 bid,
        "fonte":              "OpenCoesione",
        "tipo":               tipo,
        "titolo":             titolo[:500],
        "descrizione":        prog.get("asse_descrizione", titolo)[:2000] or None,
        "ente_nome":          prog.get("ente_programmatore", "OpenCoesione / Fondi UE"),
        "ente_paese":         "IT",
        "importo_min":        None,
        "importo_max":        None,
        "importo_stimato":    importo,
        "valuta":             "EUR",
        "data_pubblicazione": None,
        "data_scadenza":      None,
        "stato":              "attivo",
        "url_originale":      prog.get("url", f"https://opencoesione.gov.it"),
        "url_pdf":            None,
        "cpv_codes":          [],
        "settori":            settori,
        "destinatari":        dest,
        "_raw":               {"codice": codice, "tema": tema_slug},
    }


def _parse_progetto(proj: dict, tema_slug: str) -> dict | None:
    """Normalizza un progetto OpenCoesione come bando/opportunita'."""
    cup    = proj.get("cup", "")
    titolo = proj.get("oc_titolo_progetto", "").strip()
    if not titolo:
        return None

    stato_raw = proj.get("oc_stato_progetto", "").lower()
    stato = "attivo" if "in corso" in stato_raw or "approvato" in stato_raw else "scaduto"

    tipo, settori = TEMI.get(tema_slug, ("incentivo_imprese", [tema_slug]))
    dest          = DESTINATARI_TEMA.get(tema_slug, ["aziende"])

    importo = None
    fin = proj.get("oc_finanz_tot_pub_netto")
    if fin:
        try:
            importo = float(str(fin).replace(".", "").replace(",", "."))
        except ValueError:
            pass

    bid = f"OC-{cup}" if cup else f"OC-{abs(hash(titolo)) % 10**8}"

    # Soggetti beneficiari come testo descrittivo
    soggetti = proj.get("soggetti", [])
    beneficiari = ", ".join(
        s.get("denominazione", "") for s in soggetti
        if "Beneficiary" in s.get("ruoli", [])
    )[:300]

    descrizione = titolo
    if beneficiari:
        descrizione += f" | Beneficiari: {beneficiari}"

    return {
        "id":                 bid,
        "fonte":              "OpenCoesione",
        "tipo":               tipo,
        "titolo":             titolo[:500],
        "descrizione":        descrizione[:2000],
        "ente_nome":          soggetti[0].get("denominazione", "PA") if soggetti else "PA",
        "ente_paese":         "IT",
        "importo_min":        None,
        "importo_max":        None,
        "importo_stimato":    importo,
        "valuta":             "EUR",
        "data_pubblicazione": None,
        "data_scadenza":      None,
        "stato":              stato,
        "url_originale":      proj.get("url", "https://opencoesione.gov.it"),
        "url_pdf":            None,
        "cpv_codes":          [],
        "settori":            settori,
        "destinatari":        dest,
        "_raw":               {"cup": cup, "tema": tema_slug,
                               "ciclo": proj.get("oc_descr_ciclo", "")},
    }


def scrape_opencoesione_programmi(verbose: bool = True) -> int:
    """
    Importa i programmi di finanziamento (PNRR, PON, POR, ecc.) come bandi.
    Sono le 'cornici' dei fondi strutturali — utili per matching a livello macro.
    """
    data = _get(f"{OC_BASE}/programmi/", {"format": "json", "page_size": 200})
    if not data:
        return 0

    progs = data.get("objects", data.get("results", []))
    total = 0
    for prog in progs:
        # Determina tema dal codice programma (best-effort)
        codice = (prog.get("codice") or "").upper()
        if "RICER" in codice or "INNOV" in codice:
            tema = "ricerca-e-innovazione"
        elif "DIGIT" in codice:
            tema = "reti-servizi-digitali"
        elif "IMPRE" in codice or "COMP" in codice:
            tema = "competitivita-imprese"
        else:
            tema = "capacita-amministrativa"

        bando = _parse_programma(prog, tema)
        if bando:
            upsert_bando(bando)
            total += 1

    if verbose:
        print(f"[OC] Programmi importati: {total}")
    return total


def scrape_opencoesione_progetti(
    temi: list = None,
    max_per_tema: int = 200,
    solo_attivi: bool = True,
    verbose: bool = True,
) -> int:
    """
    Importa progetti OpenCoesione per tema come bandi/opportunita'.

    Args:
        temi:         lista slug temi (default: tutti gli 11 temi)
        max_per_tema: max progetti per tema
        solo_attivi:  filtra solo progetti in corso / approvati
        verbose:      stampa progressi

    Returns:
        Numero di bandi importati
    """
    if temi is None:
        temi = list(TEMI.keys())

    total = 0

    for tema in temi:
        if verbose:
            print(f"[OC] Tema: {tema}")

        params = {
            "format":    "json",
            "tema":      tema,
            "page_size": 50,
        }

        page_total = 0
        url = f"{OC_BASE}/progetti/"

        while page_total < max_per_tema:
            data = _get(url, params)
            if not data:
                break

            risultati = data.get("results", data.get("objects", []))
            if not risultati:
                break

            for proj in risultati:
                if page_total >= max_per_tema:
                    break
                bando = _parse_progetto(proj, tema)
                if bando:
                    upsert_bando(bando)
                    page_total += 1

            # Paginazione
            next_url = data.get("next")
            if not next_url or page_total >= max_per_tema:
                break

            url    = next_url.split("?")[0]
            params = {"format": "json"}
            time.sleep(0.3)

        if verbose:
            print(f"[OC]   -> {page_total} progetti")
        total += page_total

    print(f"[OC] Totale importato: {total} bandi OpenCoesione")
    return total


def scrape_opencoesione(
    max_per_tema: int = 100,
    temi: list = None,
    verbose: bool = True,
) -> int:
    """Entry point principale."""
    n_prog = scrape_opencoesione_programmi(verbose)
    n_proj = scrape_opencoesione_progetti(
        temi=temi,
        max_per_tema=max_per_tema,
        verbose=verbose,
    )
    return n_prog + n_proj


if __name__ == "__main__":
    init_db()
    scrape_opencoesione(max_per_tema=50)
