"""
Motore di matching bandi -> entita.

Score composito (0..1):
  tipo_score     0.30  tipo entita vs destinatari bando
  settori_score  0.20  oc_tema/segnali entita vs settori bando
  concept_score  0.15  openalex concepts vs settori bando
  keyword_score  0.10  overlap parole chiave titolo/desc
  peso_score     0.15  peso entita (h_index/citations/n_progetti/n_repos)
  geo_score      0.10  match territoriale bando.regione vs entita.sede_regione

Ogni coppia (bando, entita) produce un dict dettaglio + score finale.
"""
import re
import sqlite3
import json
from math import log10
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "db" / "bandi.db"

# --- Pesi score componenti ------------------------------------------------
W = {
    "tipo":    0.30,
    "settori": 0.20,
    "concept": 0.15,
    "keyword": 0.10,
    "peso":    0.15,
    "geo":     0.10,
}

# --- Mapping tipo entita → slug destinatari compatibili ------------------
TIPO_DEST: dict[str, set[str]] = {
    "azienda":       {"aziende", "startup", "pmi", "imprese", "software_house"},
    "universita":    {"universita", "universit�", "universit\xe0", "enti_formazione"},
    "ente_ricerca":  {"enti_ricerca", "centri_ricerca", "universita"},
    "ricercatore":   {"ricercatori", "enti_ricerca", "universita"},
    "ente_pubblico": {"pa", "enti_pubblici", "comuni", "enti_sanitari"},
}
# normalizza varianti encoding
_UNIVERSITA_VARIANTS = {"universit�", "universit\xe0", "universita"}

def _norm_tipo(tipo: str) -> str:
    if tipo in _UNIVERSITA_VARIANTS:
        return "universita"
    return tipo

# --- Mapping oc_tema slug → settori bando compatibili ---------------------
OC_TEMA_SETTORI: dict[str, set[str]] = {
    "ricerca-e-innovazione":   {"ricerca", "innovazione", "fisica", "scienze_vita",
                                 "scienze_sociali"},
    "reti-servizi-digitali":   {"tecnologia", "digitale"},
    "competitivita-imprese":   {"imprese", "innovazione", "tecnologia"},
    "energia":                 {"energia", "ambiente"},
    "ambiente":                {"ambiente"},
    "cultura-e-turismo":       {"cultura", "turismo"},
    "trasporti":               {"trasporti", "infrastrutture"},
    "occupazione":             {"lavoro", "formazione"},
    "inclusione-sociale":      {"sociale", "salute"},
    "istruzione":              {"istruzione", "formazione"},
    "capacita-amministrativa": {"pubblica_amministrazione"},
}

# --- Mapping settore bando → keyword English (per concept matching) -------
SETTORE_ENG: dict[str, set[str]] = {
    "ricerca":             {"research", "physics", "biology", "chemistry",
                            "mathematics", "science", "scientific"},
    "innovazione":         {"innovation", "technology", "engineering", "startup"},
    "tecnologia":          {"technology", "computer", "software", "computing"},
    "digitale":            {"digital", "computer", "software", "information",
                            "data", "artificial intelligence", "machine learning"},
    "ambiente":            {"environment", "ecology", "climate", "sustainability",
                            "geology", "atmospheric"},
    "energia":             {"energy", "renewable", "solar", "wind", "nuclear"},
    "salute":              {"medicine", "health", "biology", "medical",
                            "clinical", "pharmacology"},
    "istruzione":          {"education", "learning", "pedagogy", "teaching"},
    "lavoro":              {"labor", "employment", "economics", "management"},
    "imprese":             {"business", "management", "economics", "finance"},
    "sociale":             {"social", "sociology", "psychology", "welfare"},
    "sanita":              {"medicine", "health", "clinical", "pharmacology",
                            "nursing", "epidemiology", "pathology"},
    "salute":              {"medicine", "health", "clinical", "biology",
                            "medical", "epidemiology"},
    "cultura":             {"art", "culture", "humanities", "history", "literature"},
    "turismo":             {"tourism", "geography"},
    "formazione":          {"training", "education", "learning"},
    "trasporti":           {"transport", "logistics", "infrastructure",
                            "mechanical engineering", "automotive"},
    "infrastrutture":      {"infrastructure", "civil engineering", "construction",
                            "geotechnical engineering"},
    "fisica":              {"physics", "particle", "nuclear", "quantum"},
    "scienze_vita":        {"biology", "medicine", "biochemistry", "genetics",
                            "biotechnology", "life science"},
    "scienze_sociali":     {"sociology", "economics", "political science",
                            "psychology", "anthropology"},
    "appalto_lavori":      {"civil engineering", "construction", "architecture"},
    "pubblica_amministrativa": {"public administration", "governance", "policy"},
    "pubblica_amministrazione": {"public administration", "governance", "policy"},
}

# --- Stop-words italiane + inglesi per keyword score ---------------------
_STOP = {
    "di", "in", "il", "la", "le", "gli", "lo", "un", "una", "e", "a", "da",
    "del", "della", "dei", "delle", "degli", "per", "con", "su", "che", "si",
    "non", "ho", "hai", "ha", "hanno", "era", "sono", "erano", "questo",
    "quello", "quale", "qui", "quando", "come", "se", "ma", "o", "anche",
    "piu", "molto", "tutti", "tutto", "ogni", "ai", "al", "allo", "alla",
    "alle", "agli", "nei", "nel", "nella", "nelle", "negli", "dei", "delle",
    "the", "of", "and", "in", "to", "a", "is", "for", "on", "are", "with",
    "that", "this", "it", "by", "be", "as", "at", "an", "or", "from",
}

def _tokenize(text: str) -> set[str]:
    tokens = re.split(r"[\s\-_/,;:()\[\]]+", text.lower())
    return {t for t in tokens if len(t) >= 3 and t not in _STOP}


# =========================================================================
# Caricamento dati dal DB
# =========================================================================

def _load_bandi(con: sqlite3.Connection) -> list[dict]:
    """Carica tutti i bandi attivi con settori e destinatari."""
    rows = con.execute(
        "SELECT id, tipo, titolo, descrizione, stato, regione "
        "FROM bandi WHERE stato='attivo'"
    ).fetchall()
    bandi = []
    for r in rows:
        bid, tipo, titolo, desc, stato, regione = r
        settori = {
            s[0] for s in con.execute(
                "SELECT settore FROM bandi_settori WHERE bando_id=?", (bid,)
            )
        }
        destinatari = {
            s[0] for s in con.execute(
                "SELECT destinatario FROM bandi_destinatari WHERE bando_id=?", (bid,)
            )
        }
        # normalizza universita variants
        destinatari = {_norm_tipo(d) if d in _UNIVERSITA_VARIANTS else d
                       for d in destinatari}
        testo = f"{titolo or ''} {desc or ''}"
        bandi.append({
            "id":          bid,
            "tipo":        tipo,
            "regione":     regione,
            "settori":     settori,
            "destinatari": destinatari,
            "keywords":    _tokenize(testo),
        })
    return bandi


_METRIC_SIGNAL_TYPES = {
    "oa_works_count", "oa_citations", "oa_h_index",
    "oc_n_progetti", "oc_costo_pubblico_tot",
    "gh_n_repos", "github_community",
    "oc_fondi_strutturali",  # value e' "oc:tema:importo" — gia' coperto da oc_tema
}


def _load_entita(con: sqlite3.Connection) -> list[dict]:
    """Carica tutte le entita con segnali."""
    rows = con.execute(
        "SELECT id, tipo, nome, sede_regione FROM entita"
    ).fetchall()
    entita = []
    for r in rows:
        eid, tipo, nome, sede_regione = r
        tipo = _norm_tipo(tipo)
        segnali = con.execute(
            "SELECT tipo, valore, peso FROM segnali WHERE entita_id=?", (eid,)
        ).fetchall()
        oc_temi = set()
        concepts = set()
        extra_kw = set()
        # Metriche grezze per peso_score
        h_index = 0.0
        n_progetti = 0
        n_repos = 0
        citations = 0
        for stype, sval, speso in segnali:
            if stype == "oc_tema":
                oc_temi.add(sval)
            elif stype == "openalex_concept":
                concepts.add(sval.lower())
            elif stype == "oa_h_index":
                try: h_index = float(sval)
                except (ValueError, TypeError): pass
            elif stype == "oa_citations":
                try: citations = int(sval)
                except (ValueError, TypeError): pass
            elif stype == "oc_n_progetti":
                try: n_progetti = int(sval)
                except (ValueError, TypeError): pass
            elif stype == "gh_n_repos":
                try: n_repos = int(sval)
                except (ValueError, TypeError): pass
            elif stype in _METRIC_SIGNAL_TYPES:
                # altre metriche numeriche: skip dalle keyword
                pass
            else:
                extra_kw.update(_tokenize(str(sval)))
        keywords = _tokenize(nome) | extra_kw
        entita.append({
            "id":           eid,
            "tipo":         tipo,
            "nome":         nome,
            "sede_regione": sede_regione,
            "oc_temi":      oc_temi,
            "concepts":     concepts,
            "keywords":     keywords,
            "h_index":      h_index,
            "citations":    citations,
            "n_progetti":   n_progetti,
            "n_repos":      n_repos,
        })
    return entita


# =========================================================================
# Funzioni di scoring
# =========================================================================

def _tipo_score(bando: dict, entita: dict) -> float:
    compat = TIPO_DEST.get(entita["tipo"], set())
    dest = bando["destinatari"]
    if not dest:
        return 0.5  # bando senza destinatari → neutro
    if compat & dest:
        return 1.0
    # partial: pubblica amministrazione accetta anche enti_ricerca su certi bandi
    if entita["tipo"] in ("universita", "ente_ricerca") and "pa" in dest:
        return 0.4
    return 0.0


def _settori_score(bando: dict, entita: dict) -> float:
    """
    Logica OR: almeno 1 tema dell'entita che matcha i settori del bando
    da' un punteggio alto. Aver "anche" altri temi non e' una penalita',
    se mai un piccolo bonus (multi-tema = entita versatile / esperta).
    """
    settori = bando["settori"]
    if not settori:
        return 0.5  # bando senza settori → neutro
    if not entita["oc_temi"]:
        return 0.3  # nessun tema oc → punteggio base
    match = sum(
        1 for tema in entita["oc_temi"]
        if OC_TEMA_SETTORI.get(tema, set()) & settori
    )
    if match == 0:
        return 0.0
    # Almeno 1 match → 0.7 baseline + 0.1 per ogni match aggiuntivo (cap 1.0)
    return min(1.0, 0.7 + 0.1 * (match - 1))


def _concept_score(bando: dict, entita: dict) -> float:
    settori = bando["settori"]
    if not settori or not entita["concepts"]:
        return 0.0
    # Costruisci set keyword inglesi attese per i settori del bando
    expected_eng: set[str] = set()
    for s in settori:
        expected_eng.update(SETTORE_ENG.get(s, set()))
    if not expected_eng:
        return 0.0
    # Conta concetti entita che matchano (parziale)
    hits = 0
    for concept in entita["concepts"]:
        for eng_kw in expected_eng:
            if eng_kw in concept or concept in eng_kw:
                hits += 1
                break
    return min(1.0, hits / max(1, len(entita["concepts"])))


def _keyword_score(bando: dict, entita: dict) -> float:
    bkw = bando["keywords"]
    ekw = entita["keywords"]
    if not bkw or not ekw:
        return 0.0
    intersect = bkw & ekw
    union = bkw | ekw
    return len(intersect) / len(union)


def _geo_score(bando: dict, entita: dict) -> float:
    """
    Match territoriale bando-entita. Score:
      - 1.0 se entrambi noti e coincidenti (case-insensitive)
      - 0.0 se entrambi noti e diversi
      - 0.5 se almeno uno e' ignoto (neutro)
    """
    br = (bando.get("regione") or "").strip().lower()
    er = (entita.get("sede_regione") or "").strip().lower()
    if not br or not er:
        return 0.5
    return 1.0 if br == er else 0.0


def _peso_score(entita: dict) -> float:
    """
    Peso aggregato dell'entita derivato dalle metriche disponibili.
    Output 0..1 normalizzato. Combina log-scaled di:
      - h_index OpenAlex (universita/ricercatori): bench 50 = 1.0
      - citations OpenAlex: bench 1M = 1.0
      - n_progetti OC (aziende/enti): bench 100 = 1.0
      - n_repos GitHub: bench 1000 = 1.0
    Prende il MASSIMO tra le metriche disponibili (l'entita "vale" per la
    sua dimensione piu' forte, non per la media).
    """
    candidates = []
    if entita["h_index"] > 0:
        # h-index 50 = 1.0, 25 = 0.5, 10 ≈ 0.2
        candidates.append(min(entita["h_index"] / 50.0, 1.0))
    if entita["citations"] > 0:
        # citations 1M = 1.0, 100k ≈ 0.83, 10k ≈ 0.67
        candidates.append(min(log10(max(entita["citations"], 1)) / 6.0, 1.0))
    if entita["n_progetti"] > 0:
        # 100 progetti = 1.0, 10 = 0.5, 1 = 0.0
        candidates.append(min(log10(max(entita["n_progetti"], 1)) / 2.0, 1.0))
    if entita["n_repos"] > 0:
        # 1000 repo = 1.0, 100 = 0.67, 10 = 0.33
        candidates.append(min(log10(max(entita["n_repos"], 1)) / 3.0, 1.0))
    if not candidates:
        return 0.3  # entita senza metriche → punteggio base neutro
    return max(candidates)


# =========================================================================
# Entry point pubblico
# =========================================================================

def score_bando_entita(bando: dict, entita: dict) -> dict:
    """Calcola score composito per una coppia (bando, entita)."""
    ts = _tipo_score(bando, entita)
    ss = _settori_score(bando, entita)
    cs = _concept_score(bando, entita)
    ks = _keyword_score(bando, entita)
    ps = _peso_score(entita)
    gs = _geo_score(bando, entita)
    score = (W["tipo"]    * ts
           + W["settori"] * ss
           + W["concept"] * cs
           + W["keyword"] * ks
           + W["peso"]    * ps
           + W["geo"]     * gs)
    return {
        "score":    round(score, 4),
        "tipo":     round(ts, 3),
        "settori":  round(ss, 3),
        "concept":  round(cs, 3),
        "keyword":  round(ks, 3),
        "peso":     round(ps, 3),
        "geo":      round(gs, 3),
    }


def compute_all_scores(
    min_score: float = 0.15,
    top_n: int = 20,
    verbose: bool = True,
) -> int:
    """
    Calcola match_scores per tutte le coppie (bando attivo, entita).

    Args:
        min_score: soglia minima score per salvare
        top_n:     max match per bando salvati nel DB
        verbose:   stampa progressi

    Returns:
        Numero di righe scritte in match_scores
    """
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")

    if verbose:
        print("[Match] Caricamento dati...")
    bandi   = _load_bandi(con)
    entita  = _load_entita(con)
    if verbose:
        print(f"[Match]   {len(bandi)} bandi attivi, {len(entita)} entita")

    # Cancella tutti i match precedenti (ricalcolo completo)
    con.execute("DELETE FROM match_scores")
    con.commit()

    total_written = 0

    for i, bando in enumerate(bandi):
        scored = []
        for ent in entita:
            res = score_bando_entita(bando, ent)
            if res["score"] >= min_score:
                scored.append((ent["id"], res))

        # ordina e tronca al top_n
        scored.sort(key=lambda x: x[1]["score"], reverse=True)
        scored = scored[:top_n]

        rows = [
            (bando["id"], eid, det["score"], json.dumps(det))
            for eid, det in scored
        ]
        con.executemany(
            """INSERT OR REPLACE INTO match_scores
               (bando_id, entita_id, score, dettaglio_json, calcolato_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            rows,
        )
        con.commit()
        total_written += len(rows)

        if verbose and (i + 1) % 50 == 0:
            print(f"[Match]   {i + 1}/{len(bandi)} bandi elaborati...")

    con.close()
    if verbose:
        print(f"[Match] Completato: {total_written} match salvati "
              f"({len(bandi)} bandi x top-{top_n})")
    return total_written
