"""
Scraper GitHub — profili organizzazioni tech italiane.
API pubblica (non autenticata: 60 req/h; con token: 5000 req/h).
Utile per segnali su software house, spinoff universitari, startup deep-tech.
"""
import os
import time
import requests
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.db import init_db
from entity.entity_db import upsert_entita, upsert_segnale

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # opzionale
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    _HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def _get(endpoint: str, params: dict = None) -> dict | None:
    try:
        r = requests.get(f"{GITHUB_API}/{endpoint}",
                         params=params, headers=_HEADERS, timeout=20)
        if r.status_code == 403:
            print("[GitHub] Rate limit raggiunto — imposta GITHUB_TOKEN")
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"[GitHub] Errore {endpoint}: {e}")
        return None


def _parse_org(org: dict) -> dict:
    return {
        "tipo":         "azienda",
        "nome":         org.get("name") or org.get("login", ""),
        "sito_web":     org.get("blog") or org.get("html_url"),
        "sede_citta":   _parse_location(org.get("location", "")),
        "paese":        "IT",
        "email":        org.get("email"),
        "_gh_login":    org.get("login"),
        "_gh_topics":   [],
        "_description": org.get("description") or "",
        "_repos":       org.get("public_repos", 0),
        "_followers":   org.get("followers", 0),
        "_twitter":     org.get("twitter_username"),
    }


def _parse_location(loc: str) -> str | None:
    """Estrae la città da una stringa location GitHub (best-effort)."""
    if not loc:
        return None
    # Prende l'ultima parte (es. "Milano, Italia" → "Milano")
    parts = [p.strip() for p in loc.replace(",", "|").split("|") if p.strip()]
    return parts[0] if parts else None


def scrape_github_orgs(
    query: str = "location:Italy type:org language:python",
    max_orgs: int = 200,
    verbose: bool = True,
) -> int:
    """
    Cerca organizzazioni GitHub italiane e salva il profilo nel DB.

    Args:
        query:    query GitHub search (https://docs.github.com/en/search-github)
        max_orgs: limite entità da importare
        verbose:  stampa progressi

    Returns:
        Numero di entità salvate
    """
    total = 0
    page  = 1

    while total < max_orgs:
        data = _get("search/users", {
            "q":        query,
            "type":     "org",
            "per_page": min(100, max_orgs - total),
            "page":     page,
        })
        if not data:
            break

        items = data.get("items", [])
        if not items:
            break

        for item in items:
            login = item.get("login")
            if not login:
                continue

            # Dettaglio org
            org = _get(f"orgs/{login}")
            if not org:
                time.sleep(1)
                continue

            parsed = _parse_org(org)

            # Topics dei repo principali (segnali settore)
            repos_data = _get(f"orgs/{login}/repos",
                               {"sort": "stars", "per_page": 10})
            topics = []
            if repos_data:
                for repo in repos_data:
                    topics.extend(repo.get("topics", []))
            topics = list(set(topics))
            parsed["_gh_topics"] = topics

            eid = upsert_entita(parsed)

            # Segnale: linguaggi/topic GitHub
            for t in topics[:15]:
                upsert_segnale(eid, "github_topic", t,
                               peso=0.6, fonte="GitHub",
                               raw={"login": login})

            # Segnale: descrizione testuale dell'organizzazione
            # (settore implicito + keyword utili al matching)
            descr = parsed.get("_description") or ""
            if descr:
                upsert_segnale(eid, "gh_description", descr[:500],
                               peso=0.5, fonte="GitHub",
                               raw={"login": login})

            # Segnale: linguaggi principali dei top repo (tech stack)
            if repos_data:
                langs = {}
                for repo in repos_data:
                    lang = repo.get("language")
                    if lang:
                        langs[lang] = langs.get(lang, 0) + 1
                for lang, n in langs.items():
                    upsert_segnale(eid, "gh_language", lang,
                                   peso=float(n) * 0.3, fonte="GitHub")

            # Segnale: numero repo pubblici (peso azienda)
            n_repos = parsed.get("_repos") or 0
            if n_repos > 0:
                from math import log10
                upsert_segnale(eid, "gh_n_repos", str(n_repos),
                               peso=round(log10(max(n_repos, 1)), 2),
                               fonte="GitHub")

            # Segnale: dimensione community (follower)
            if org.get("followers", 0) > 100:
                upsert_segnale(eid, "github_community",
                               f"followers:{org['followers']}",
                               peso=0.4, fonte="GitHub")

            total += 1
            time.sleep(0.5)  # rispetta rate limit

        if verbose:
            print(f"[GitHub] {total} organizzazioni importate...")

        if len(items) < 100:
            break
        page += 1

    print(f"[GitHub] Completato: {total} organizzazioni salvate")
    return total


# Query preset per diversi profili tech italiani
GITHUB_QUERIES = {
    "python_it":   "location:Italy type:org language:python",
    "research_it": "location:Italy type:org topic:research",
    "ml_it":       "location:Italy type:org topic:machine-learning",
    "spinoff_it":  "location:Italy type:org topic:university",
}

if __name__ == "__main__":
    init_db()
    scrape_github_orgs(query=GITHUB_QUERIES["python_it"], max_orgs=100)
