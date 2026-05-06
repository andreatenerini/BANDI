"""Entity module — profili aziende, ricercatori, enti di ricerca."""
from .entity_db import (
    upsert_entita,
    upsert_segnale,
    upsert_contratto_vinto,
    upsert_pubblicazione,
    get_entita,
    count_entita,
)

__all__ = [
    "upsert_entita", "upsert_segnale",
    "upsert_contratto_vinto", "upsert_pubblicazione",
    "get_entita", "count_entita",
]
