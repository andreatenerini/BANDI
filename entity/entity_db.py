"""
Operazioni DB specifiche per entità (aziende, ricercatori, enti).
Usa la stessa connessione SQLite di scraper/db.py.
"""
import json
import hashlib
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.db import get_conn


def _make_id(tipo: str, nome: str, piva: str = None) -> str:
    if piva:
        return f"{tipo.upper()}-{piva}"
    h = hashlib.md5(nome.lower().strip().encode()).hexdigest()[:10]
    return f"{tipo.upper()}-{h}"


def upsert_entita(e: dict) -> str:
    """
    Inserisce o aggiorna un'entità.
    Restituisce l'id usato.

    Campi attesi in e:
        tipo, nome, piva?, ateco?, dimensione?,
        sede_citta?, sede_regione?, paese?, sito_web?, email?
    """
    conn = get_conn()
    now = datetime.utcnow().isoformat()

    eid = e.get("id") or _make_id(e["tipo"], e["nome"], e.get("piva"))

    conn.execute("""
        INSERT INTO entita
            (id, tipo, nome, piva, ateco, dimensione,
             sede_citta, sede_regione, paese, sito_web, email,
             created_at, updated_at)
        VALUES
            (:id, :tipo, :nome, :piva, :ateco, :dimensione,
             :sede_citta, :sede_regione, :paese, :sito_web, :email,
             :created_at, :updated_at)
        ON CONFLICT(id) DO UPDATE SET
            nome=COALESCE(NULLIF(excluded.nome, ''), nome),
            piva=COALESCE(excluded.piva, piva),
            ateco=COALESCE(excluded.ateco, ateco),
            dimensione=COALESCE(excluded.dimensione, dimensione),
            sede_citta=COALESCE(excluded.sede_citta, sede_citta),
            sede_regione=COALESCE(excluded.sede_regione, sede_regione),
            sito_web=COALESCE(excluded.sito_web, sito_web),
            email=COALESCE(excluded.email, email),
            updated_at=excluded.updated_at
    """, {
        "id":           eid,
        "tipo":         e.get("tipo", "azienda"),
        "nome":         e.get("nome", ""),
        "piva":         e.get("piva"),
        "ateco":        e.get("ateco"),
        "dimensione":   e.get("dimensione"),
        "sede_citta":   e.get("sede_citta"),
        "sede_regione": e.get("sede_regione"),
        "paese":        e.get("paese", "IT"),
        "sito_web":     e.get("sito_web"),
        "email":        e.get("email"),
        "created_at":   now,
        "updated_at":   now,
    })
    conn.commit()
    conn.close()
    return eid


def upsert_segnale(entita_id: str, tipo: str, valore: str,
                   peso: float = 1.0, fonte: str = None,
                   data_rilevazione: str = None, raw: dict = None):
    """Aggiunge un segnale di interesse a un'entità (idempotente su tipo+valore)."""
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM segnali WHERE entita_id=? AND tipo=? AND valore=?",
        (entita_id, tipo, valore)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE segnali SET peso=?, fonte=?, data_rilevazione=?, raw=? WHERE id=?",
            (peso, fonte, data_rilevazione,
             json.dumps(raw, ensure_ascii=False) if raw else None,
             existing["id"])
        )
    else:
        conn.execute(
            """INSERT INTO segnali
               (entita_id, tipo, valore, peso, fonte, data_rilevazione, raw)
               VALUES (?,?,?,?,?,?,?)""",
            (entita_id, tipo, valore, peso, fonte, data_rilevazione,
             json.dumps(raw, ensure_ascii=False) if raw else None)
        )
    conn.commit()
    conn.close()


def upsert_contratto_vinto(c: dict):
    """Inserisce o aggiorna un contratto vinto."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO contratti_vinti
            (id, entita_id, cpv, importo, ente_appaltante, anno, fonte)
        VALUES
            (:id, :entita_id, :cpv, :importo, :ente_appaltante, :anno, :fonte)
        ON CONFLICT(id) DO UPDATE SET
            importo=excluded.importo,
            ente_appaltante=excluded.ente_appaltante
    """, c)
    conn.commit()
    conn.close()


def upsert_pubblicazione(p: dict):
    """Inserisce o aggiorna una pubblicazione scientifica."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO pubblicazioni
            (id, entita_id, titolo, anno, concetti_json, doi, fonte, openalex_id)
        VALUES
            (:id, :entita_id, :titolo, :anno, :concetti_json, :doi, :fonte, :openalex_id)
        ON CONFLICT(id) DO UPDATE SET
            titolo=excluded.titolo,
            concetti_json=excluded.concetti_json
    """, {**p, "concetti_json": json.dumps(p.get("concetti", []), ensure_ascii=False)})
    conn.commit()
    conn.close()


def get_entita(eid: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM entita WHERE id=?", (eid,)).fetchone()
    if not row:
        conn.close()
        return None
    result = dict(row)
    result["segnali"] = [
        dict(r) for r in
        conn.execute("SELECT * FROM segnali WHERE entita_id=?", (eid,)).fetchall()
    ]
    result["contratti"] = [
        dict(r) for r in
        conn.execute("SELECT * FROM contratti_vinti WHERE entita_id=?", (eid,)).fetchall()
    ]
    result["pubblicazioni"] = [
        dict(r) for r in
        conn.execute("SELECT * FROM pubblicazioni WHERE entita_id=?", (eid,)).fetchall()
    ]
    conn.close()
    return result


def count_entita() -> int:
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM entita").fetchone()[0]
    conn.close()
    return n
