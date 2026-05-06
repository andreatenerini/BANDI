"""Motore di matching bandi → entità."""
from .match_engine import compute_all_scores, score_bando_entita
from .run_matching import run_matching

__all__ = ["compute_all_scores", "score_bando_entita", "run_matching"]
