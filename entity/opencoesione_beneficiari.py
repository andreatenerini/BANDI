"""
Estrae soggetti beneficiari da OpenCoesione come segnali entita'.
Ogni soggetto che ha ricevuto fondi PNRR/FESR/FSE+ e' un segnale
di livello 5 (hanno gia' vinto/ricevuto fondi pubblici strutturali).

Per ogni soggetto vengono recuperati anche i dati dettagliati:
- codice fiscale, sede (citta+regione)
- TUTTI i temi su cui ha lavorato (multi-tema, con conteggi e importi)
- aggregato totale progetti e finanziamenti

API: https://opencoesione.gov.it/it/api/soggetti/
"""
import json
import time
import requests
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.db import init_db
from entity.entity_db import upsert_entita, upsert_segnale

OC_BASE  = "https://opencoesione.gov.it/it/api"
HEADERS  = {
    "User-Agent": "BANDI-scraper/1.0",
    "Accept":     "application/json",
}

# Tipi ANAC/OpenCoesione → tipo entita DB
NATURA_TO_TIPO = {
    "Universita":                     "universita",
    "Universita e Istituti":          "universita",
    "Enti di ricerca":                "ente_ricerca",
    "Centri di ricerca":              "ente_ricerca",
    "Imprese private":                "azienda",
    "Societa miste":                  "azienda",
    "Societa di capitali":            "azienda",
    "Cooperative":                    "azienda",
    "Fondazioni":                     "ente_ricerca",
    "Regioni":                        "ente_pubblico",
    "Comuni":                         "ente_pubblico",
    "Province":                       "ente_pubblico",
    "Ministeri":                      "ente_pubblico",
}

# Codici ISTAT regioni (cod_reg) → nome regione
ISTAT_REGIONI = {
    1:  "Piemonte",          2:  "Valle d'Aosta",
    3:  "Lombardia",         4:  "Trentino-Alto Adige",
    5:  "Veneto",            6:  "Friuli-Venezia Giulia",
    7:  "Liguria",           8:  "Emilia-Romagna",
    9:  "Toscana",           10: "Umbria",
    11: "Marche",            12: "Lazio",
    13: "Abruzzo",           14: "Molise",
    15: "Campania",          16: "Puglia",
    17: "Basilicata",        18: "Calabria",
    19: "Sicilia",           20: "Sardegna",
}


def _get(url: str, params: dict = None, timeout: int = 90,
         retries: int = 4) -> dict | None:
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            # Backoff specifico per 429 Too Many Requests
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "0")) or (5 * (2 ** attempt))
                if attempt < retries:
                    time.sleep(min(wait, 60))
                    continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_err = e
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
    print(f"[OC-E] Errore (dopo {retries + 1} tentativi): {last_err}")
    return None


def _tipo_from_natura(natura: str) -> str:
    for key, tipo in NATURA_TO_TIPO.items():
        if key.lower() in natura.lower():
            return tipo
    return "azienda"


def _enrich_from_detail(slug: str, eid: str, tipo: str,
                        fallback_tema: str = None) -> dict:
    """
    Recupera /api/soggetti/<slug>/ e ne estrae:
      - codice_fiscale, sede (citta + regione da ISTAT cod_reg)
      - aggregati.totali (numero progetti + costo pubblico)
      - aggregati.temi.<slug> (tutti i temi con conteggi e importi)

    Aggiorna `entita` con piva/sede e inserisce segnali multi-tema.

    Returns: dict con statistiche {'temi': N, 'piva': bool, 'sede': bool}
    """
    stats = {"temi": 0, "piva": False, "sede": False}
    detail = _get(f"{OC_BASE}/soggetti/{slug}/", {"format": "json"})
    if not detail:
        return stats

    cf       = detail.get("codice_fiscale")
    territ   = detail.get("territorio") or {}
    citta    = territ.get("denominazione")
    cod_reg  = territ.get("cod_reg")
    regione  = ISTAT_REGIONI.get(cod_reg) if cod_reg else None

    # Aggiorna l'entita con i campi mancanti (piva, sede)
    upsert_entita({
        "id":           eid,
        "tipo":         tipo,
        "nome":         detail.get("denominazione") or "",
        "piva":         cf,
        "sede_citta":   citta,
        "sede_regione": regione,
        "paese":        "IT",
    })
    stats["piva"] = bool(cf)
    stats["sede"] = bool(citta or regione)

    aggr   = detail.get("aggregati") or {}
    totali = aggr.get("totali") or {}

    # Segnale: numero progetti totali (peso del soggetto)
    n_prog = totali.get("progetti")
    if n_prog and str(n_prog).isdigit() and int(n_prog) > 0:
        upsert_segnale(
            eid, "oc_n_progetti", str(n_prog),
            peso=float(min(int(n_prog), 50)),
            fonte="OpenCoesione",
        )

    # Segnale: costo pubblico totale ricevuto (importo totale)
    costo = totali.get("costo_pubblico")
    if costo:
        upsert_segnale(
            eid, "oc_costo_pubblico_tot", str(costo).replace(",", "."),
            peso=1.0, fonte="OpenCoesione",
        )

    # Segnali multi-tema: tutti i temi con almeno 1 progetto
    temi_dict = aggr.get("temi") or {}
    for tema_slug, tema_info in temi_dict.items():
        t_totali = (tema_info or {}).get("totali") or {}
        n = t_totali.get("progetti")
        if not n or not str(n).isdigit() or int(n) <= 0:
            continue
        n_int = int(n)
        # Peso proporzionale al numero progetti, capped a 10
        upsert_segnale(
            eid, "oc_tema", tema_slug,
            peso=float(min(n_int * 1.0, 10.0)),
            fonte="OpenCoesione",
            raw={
                "label":          (tema_info or {}).get("label"),
                "n_progetti":     n_int,
                "costo_pubblico": t_totali.get("costo_pubblico"),
            },
        )
        stats["temi"] += 1

    # Fallback: se l'API non torna temi e abbiamo un tema dal listing, salvalo
    if stats["temi"] == 0 and fallback_tema:
        upsert_segnale(
            eid, "oc_tema", fallback_tema,
            peso=2.0, fonte="OpenCoesione",
        )

    return stats


def import_opencoesione_beneficiari(
    tema: str = None,
    max_soggetti: int = 1000,
    verbose: bool = True,
    seen_slugs: set = None,
) -> int:
    """
    Importa soggetti beneficiari OpenCoesione come entita' nel DB.
    Per ogni soggetto fa ANCHE una chiamata a /soggetti/<slug>/ per arricchire
    con piva, sede, multi-tema, totali progetti.

    Args:
        tema:          slug tema per filtrare (None = tutti)
                       es: 'ricerca-e-innovazione', 'competitivita-imprese'
        max_soggetti:  limite entita' da importare
        verbose:       stampa progressi
        seen_slugs:    set condiviso per evitare detail-fetch ripetuti
                       (un soggetto puo' apparire in piu' temi)

    Returns:
        Numero di entita' importate/aggiornate (incluse quelle gia' viste)
    """
    if seen_slugs is None:
        seen_slugs = set()

    params = {"format": "json", "page_size": 100}
    if tema:
        params["tema"] = tema

    url   = f"{OC_BASE}/soggetti/"
    total = 0
    new_total = 0

    while total < max_soggetti:
        data = _get(url, params)
        if not data:
            break

        soggetti = data.get("results", data.get("objects", []))
        if not soggetti:
            break

        for sogg in soggetti:
            if total >= max_soggetti:
                break

            denominazione = (sogg.get("denominazione") or "").strip()
            if not denominazione:
                continue

            slug = sogg.get("slug")
            natura   = sogg.get("ruolo") or sogg.get("natura_giuridica") or ""
            tipo     = _tipo_from_natura(natura)
            url_sogg = sogg.get("url", "")

            eid = upsert_entita({
                "tipo":  tipo,
                "nome":  denominazione,
                "paese": "IT",
            })

            # Segnale primario (compatibilita' col matcher esistente)
            importo_raw = sogg.get("tot_pagamenti") or sogg.get("oc_finanz_tot_pub_netto")
            segnale_val = f"oc:{tema or 'all'}:{str(importo_raw or '')[:20]}"
            upsert_segnale(
                eid, "oc_fondi_strutturali", segnale_val,
                peso=3.0, fonte="OpenCoesione",
                raw={"tema": tema, "natura": natura,
                     "importo": importo_raw, "url": url_sogg},
            )

            # Detail-fetch (skip se gia' fatto in questo run)
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                stats = _enrich_from_detail(slug, eid, tipo, fallback_tema=tema)
                new_total += 1
                if verbose and new_total % 50 == 0:
                    print(f"[OC-E]   detail: {new_total} arricchiti "
                          f"(ultimo: temi={stats['temi']} piva={stats['piva']})")
                time.sleep(0.15)
            elif tema:
                # gia' visto in altro tema: aggiungi solo il tema mancante
                upsert_segnale(eid, "oc_tema", tema, peso=2.0,
                               fonte="OpenCoesione")

            total += 1

        if verbose and total % 200 == 0 and total > 0:
            print(f"[OC-E] {total} soggetti processati (tema={tema})")

        next_url = data.get("next")
        if not next_url:
            break

        url    = next_url.split("?")[0]
        params = {"format": "json", "page_size": 100}
        if tema:
            params["tema"] = tema
        time.sleep(0.2)

    print(f"[OC-E] Completato: {total} soggetti (tema={tema or 'tutti'}) "
          f"di cui {new_total} con detail-fetch")
    return total


def import_all_temi(
    temi: list = None,
    max_per_tema: int = 200,
    verbose: bool = True,
) -> int:
    """
    Importa beneficiari per tutti i temi prioritari.
    Temi predefiniti: ricerca, innovazione, imprese (piu' rilevanti per matching).
    """
    if temi is None:
        temi = [
            "ricerca-e-innovazione",
            "competitivita-imprese",
            "reti-servizi-digitali",
            "ambiente",
            "istruzione",
        ]

    total = 0
    seen_slugs: set = set()
    for t in temi:
        if verbose:
            print(f"[OC-E] Tema: {t}")
        n = import_opencoesione_beneficiari(
            tema=t,
            max_soggetti=max_per_tema,
            verbose=verbose,
            seen_slugs=seen_slugs,
        )
        if verbose:
            print(f"[OC-E]   -> {n} soggetti (dedup pool: {len(seen_slugs)})")
        total += n

    return total


if __name__ == "__main__":
    init_db()
    import_all_temi(max_per_tema=100)
