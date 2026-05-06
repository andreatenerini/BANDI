"""
Scraper MUR — Ministero dell'Università e della Ricerca
Bandi PRIN e altri programmi di finanziamento alla ricerca.
Metodo: HTML scraping (nessuna API pubblica disponibile).
"""
import json
import time
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

from .config import MUR_BANDI_URL, MUR_RAW_DIR, HEADERS, TIMEOUT
from .db import upsert_bando, init_db

MUR_RAW_DIR.mkdir(parents=True, exist_ok=True)

MUR_URLS = {
    "finanziamenti": "https://www.mur.gov.it/it/aree-tematiche/ricerca/programmi-di-finanziamento",
    "prin":          "https://www.mur.gov.it/it/aree-tematiche/ricerca/programmi-di-finanziamento/progetti-di-rilevante-interesse-nazionale-prin",
    "news_ricerca":  "https://www.mur.gov.it/it/news",
}

PRIN_PORTAL = "https://prin.mur.gov.it/"


def _extract_date(text: str) -> str | None:
    """Estrae una data in formato ISO da testo libero."""
    patterns = [
        r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})",   # gg/mm/aaaa
        r"(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})",   # aaaa-mm-gg
        r"(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|"
        r"luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(\d{4})",
    ]
    mesi = {"gennaio":"01","febbraio":"02","marzo":"03","aprile":"04",
            "maggio":"05","giugno":"06","luglio":"07","agosto":"08",
            "settembre":"09","ottobre":"10","novembre":"11","dicembre":"12"}
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            g = m.groups()
            try:
                if len(g) == 3 and g[1] in mesi:
                    return f"{g[2]}-{mesi[g[1]]}-{int(g[0]):02d}"
                elif len(g) == 3 and len(g[2]) == 4:
                    return f"{g[2]}-{int(g[1]):02d}-{int(g[0]):02d}"
                elif len(g) == 3 and len(g[0]) == 4:
                    return f"{g[0]}-{int(g[1]):02d}-{int(g[2]):02d}"
            except (ValueError, KeyError):
                pass
    return None


def _extract_importo(text: str) -> float | None:
    """Estrae un importo in euro da testo libero."""
    patterns = [
        r"([\d\.]+(?:,\d+)?)\s*(?:milioni?|mln)",
        r"€\s*([\d\.]+(?:,\d+)?)",
        r"([\d\.]+(?:,\d+)?)\s*euro",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                val = float(raw)
                if "milion" in pat or "mln" in pat:
                    val *= 1_000_000
                return val
            except ValueError:
                pass
    return None


def _fetch(url: str) -> BeautifulSoup | None:
    """Scarica una pagina e restituisce il BeautifulSoup."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return BeautifulSoup(r.text, "lxml")
    except requests.RequestException as e:
        print(f"[MUR] Errore {url}: {e}")
        return None


def _scrape_mur_finanziamenti() -> list:
    """Scrape la pagina principale programmi di finanziamento MUR."""
    bandi = []
    soup = _fetch(MUR_URLS["finanziamenti"])
    if not soup:
        return bandi

    # Cerca tutti i link a bandi/programmi
    for a in soup.find_all("a", href=True):
        href = a["href"]
        testo = a.get_text(strip=True)
        if not testo or len(testo) < 10:
            continue

        # Filtra link rilevanti
        keywords = ["prin", "bando", "programm", "finanziamento", "grant",
                    "ricerca", "innovazion", "horizon", "pnrr"]
        if not any(kw in testo.lower() or kw in href.lower() for kw in keywords):
            continue

        # Costruisce URL assoluto
        if href.startswith("/"):
            href = "https://www.mur.gov.it" + href
        elif not href.startswith("http"):
            continue

        bandi.append({"url": href, "titolo_link": testo})

    return bandi


def _scrape_bando_detail(url: str, titolo_hint: str = "") -> dict | None:
    """Scrape una pagina di dettaglio bando MUR."""
    soup = _fetch(url)
    if not soup:
        return None

    # Titolo: <h1> o <h2> principale
    titolo = ""
    for tag in ["h1", "h2"]:
        el = soup.find(tag)
        if el:
            titolo = el.get_text(strip=True)
            break
    if not titolo:
        titolo = titolo_hint

    # Testo principale
    main = soup.find("main") or soup.find("article") or soup.find("div", class_=re.compile("content|body|main"))
    testo = main.get_text(" ", strip=True) if main else soup.get_text(" ", strip=True)
    testo = re.sub(r"\s+", " ", testo)[:3000]

    importo    = _extract_importo(testo)
    scadenza   = _extract_date(testo)
    data_pubb  = None

    # Cerca data pubblicazione in meta o struttura
    meta_date = soup.find("meta", {"name": "date"}) or soup.find("time")
    if meta_date:
        raw = meta_date.get("content") or meta_date.get("datetime") or meta_date.get_text()
        data_pubb = _extract_date(raw)

    # Determina tipo
    titolo_l = titolo.lower()
    if "prin" in titolo_l:
        tipo = "ricerca_nazionale"
        destinatari = ["università", "enti_ricerca", "ricercatori"]
        settori = ["ricerca"]
    elif any(k in titolo_l for k in ["dottorat", "borsa", "fellowship"]):
        tipo = "borsa_ricerca"
        destinatari = ["ricercatori"]
        settori = ["ricerca"]
    elif any(k in titolo_l for k in ["horizon", "erc", "msca"]):
        tipo = "ricerca_europea"
        destinatari = ["università", "aziende", "ricercatori"]
        settori = ["ricerca", "innovazione"]
    else:
        tipo = "ricerca_nazionale"
        destinatari = ["università", "enti_ricerca"]
        settori = ["ricerca"]

    bid = f"MUR-{abs(hash(url)) % 10**8}"

    return {
        "id":                 bid,
        "fonte":              "MUR",
        "tipo":               tipo,
        "titolo":             titolo[:500],
        "descrizione":        testo[:2000],
        "ente_nome":          "Ministero dell'Università e della Ricerca",
        "ente_paese":         "IT",
        "importo_min":        None,
        "importo_max":        None,
        "importo_stimato":    importo,
        "valuta":             "EUR",
        "data_pubblicazione": data_pubb,
        "data_scadenza":      scadenza,
        "stato":              "attivo" if not scadenza or scadenza >= datetime.today().strftime("%Y-%m-%d") else "scaduto",
        "url_originale":      url,
        "url_pdf":            None,
        "cpv_codes":          [],
        "settori":            settori,
        "destinatari":        destinatari,
        "_raw":               {"url": url, "titolo": titolo, "testo_preview": testo[:500]},
    }


def _scrape_prin_known() -> list:
    """
    Inserisce direttamente i bandi PRIN noti (dati già verificati).
    Utile come fallback se il sito MUR è irraggiungibile o cambia struttura.
    """
    return [
        {
            "id":                 "MUR-PRIN-2026",
            "fonte":              "MUR",
            "tipo":               "ricerca_nazionale",
            "titolo":             "PRIN 2026 — Progetti di Rilevante Interesse Nazionale",
            "descrizione":        (
                "Bando per il finanziamento di progetti di ricerca fondamentale "
                "di rilevante interesse nazionale. Dotazione: €259.889.354. "
                "Aree: Life Sciences (35%), Physical Sciences & Engineering (35%), "
                "Social Sciences & Humanities (30%). "
                "Durata progetto: 3 anni, 4-6 unità di ricerca. "
                "15% risorse riservato a PI under 40."
            ),
            "ente_nome":          "MUR — Ministero dell'Università e della Ricerca",
            "ente_paese":         "IT",
            "importo_min":        1_000_000,
            "importo_max":        1_200_000,
            "importo_stimato":    259_889_354,
            "valuta":             "EUR",
            "data_pubblicazione": "2026-04-10",
            "data_scadenza":      "2026-06-01",
            "stato":              "attivo",
            "url_originale":      "https://www.mur.gov.it/it/aree-tematiche/ricerca/programmi-di-finanziamento/progetti-di-rilevante-interesse-nazionale-prin/prin-2026",
            "url_pdf":            "https://www.mur.gov.it/sites/default/files/2026-04/D.D.%20n.%202298%20del%2010-04-2026%20BANDO%20PRIN%202026.pdf",
            "cpv_codes":          [],
            "settori":            ["ricerca", "scienze_vita", "fisica", "scienze_sociali"],
            "destinatari":        ["università", "enti_ricerca", "ricercatori"],
            "_raw":               {"ref": "Decreto Direttoriale n. 2298 del 10 Aprile 2026"},
        },
        {
            "id":                 "MUR-PRIN-HYBRID-2026",
            "fonte":              "MUR",
            "tipo":               "ricerca_nazionale",
            "titolo":             "PRIN Hybrid 2026 — Progetti multidisciplinari",
            "descrizione":        (
                "Bando per progetti multidisciplinari che integrano scienze umane "
                "e nuove tecnologie. Dotazione: €56.600.000. "
                "Focalizzato su tecnologie emergenti con approccio interdisciplinare."
            ),
            "ente_nome":          "MUR — Ministero dell'Università e della Ricerca",
            "ente_paese":         "IT",
            "importo_min":        None,
            "importo_max":        None,
            "importo_stimato":    56_600_000,
            "valuta":             "EUR",
            "data_pubblicazione": "2026-04-20",
            "data_scadenza":      "2026-06-04",
            "stato":              "attivo",
            "url_originale":      "https://www.mur.gov.it/it/news/lunedi-20042026/ricerca-arriva-prin-hybrid",
            "url_pdf":            None,
            "cpv_codes":          [],
            "settori":            ["ricerca", "multidisciplinare", "tecnologie_emergenti"],
            "destinatari":        ["università", "enti_ricerca", "ricercatori"],
            "_raw":               {"ref": "Decreto Direttoriale n. 2610 del 17 Aprile 2026"},
        },
    ]


def scrape_mur(
    scrape_live: bool = True,
    include_known: bool = True,
    verbose: bool = True,
) -> int:
    """
    Scrape bandi MUR e li salva nel DB.

    Args:
        scrape_live:    tenta scraping live del sito MUR
        include_known:  inserisce bandi noti (PRIN 2026, ecc.) come fallback
        verbose:        stampa progressi

    Returns:
        Numero di bandi inseriti/aggiornati
    """
    total = 0

    # 1) Bandi noti (dati verificati)
    if include_known:
        for b in _scrape_prin_known():
            upsert_bando(b)
            total += 1
            if verbose:
                print(f"[MUR] Inserito (noto): {b['titolo'][:60]}")

    # 2) Scraping live
    if scrape_live:
        if verbose:
            print("[MUR] Scraping live pagine finanziamenti...")

        links = _scrape_mur_finanziamenti()
        if verbose:
            print(f"[MUR] Trovati {len(links)} link candidati")

        seen_urls = set()
        for item in links[:20]:  # limita a 20 per non sovraccaricare
            url = item["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            bando = _scrape_bando_detail(url, item["titolo_link"])
            if bando and bando.get("titolo"):
                upsert_bando(bando)
                total += 1
                if verbose:
                    print(f"[MUR] Scraping: {bando['titolo'][:60]}")
                time.sleep(1)  # cortesia verso il server

    print(f"[MUR] Completato: {total} bandi salvati")
    return total


if __name__ == "__main__":
    init_db()
    scrape_mur(scrape_live=True, include_known=True)
