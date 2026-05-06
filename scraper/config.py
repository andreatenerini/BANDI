"""Configurazione centrale — URL, timeout, user-agent, percorsi."""
from pathlib import Path

ROOT      = Path(__file__).parent.parent
DATA_RAW  = ROOT / "data" / "raw"
DATA_DB   = ROOT / "data" / "db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

TIMEOUT = 30   # secondi per richieste HTTP

# ── TED ───────────────────────────────────────────────────────────────────────
TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_FIELDS = [
    "ND", "TI", "notice-title", "organisation-name-buyer",
    "estimated-value-lot", "deadline-date-lot", "procedure-type",
    "classification-cpv", "description-lot", "dispatch-date",
    "place-of-performance-city-lot", "links", "form-type",
    "buyer-country", "contract-nature",
]
TED_PAGE_SIZE = 50

# ── ANAC ──────────────────────────────────────────────────────────────────────
ANAC_CATALOG_URL = "https://dati.anticorruzione.it/opendata/api/v1/dataset"
ANAC_RAW_DIR     = DATA_RAW / "anac"

# ── MUR / PRIN ────────────────────────────────────────────────────────────────
MUR_BANDI_URL    = "https://www.mur.gov.it/it/aree-tematiche/ricerca/programmi-di-finanziamento"
MUR_RAW_DIR      = DATA_RAW / "mur"
