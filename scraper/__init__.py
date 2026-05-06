"""Scraper package -- bandi pubblici da TED, OpenCoesione, MUR."""
from .db import init_db, upsert_bando, count_bandi
from .ted_scraper import scrape_ted, PRESET_QUERIES
from .mur_scraper import scrape_mur
from .opencoesione_scraper import scrape_opencoesione

__all__ = [
    "init_db", "upsert_bando", "count_bandi",
    "scrape_ted", "PRESET_QUERIES",
    "scrape_mur",
    "scrape_opencoesione",
]
