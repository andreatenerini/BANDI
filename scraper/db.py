"""
Schema SQLite per bandi e entità — unico punto di verità per tutto il progetto.
"""
import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).parent.parent / "data" / "db" / "bandi.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Crea tutte le tabelle se non esistono."""
    conn = get_conn()
    conn.executescript("""
    -- ─────────────────────────────────────────
    -- BANDI
    -- ─────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS bandi (
        id                  TEXT PRIMARY KEY,
        fonte               TEXT NOT NULL,
        tipo                TEXT NOT NULL,
        titolo              TEXT,
        descrizione         TEXT,
        ente_nome           TEXT,
        ente_paese          TEXT DEFAULT 'IT',
        regione             TEXT,
        importo_min         REAL,
        importo_max         REAL,
        importo_stimato     REAL,
        valuta              TEXT DEFAULT 'EUR',
        data_pubblicazione  TEXT,
        data_scadenza       TEXT,
        stato               TEXT DEFAULT 'attivo',
        url_originale       TEXT,
        url_pdf             TEXT,
        raw_json            TEXT,
        created_at          TEXT DEFAULT (datetime('now')),
        updated_at          TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS bandi_cpv (
        bando_id        TEXT NOT NULL REFERENCES bandi(id) ON DELETE CASCADE,
        cpv_code        TEXT NOT NULL,
        cpv_descrizione TEXT,
        PRIMARY KEY (bando_id, cpv_code)
    );

    CREATE TABLE IF NOT EXISTS bandi_settori (
        bando_id    TEXT NOT NULL REFERENCES bandi(id) ON DELETE CASCADE,
        settore     TEXT NOT NULL,
        PRIMARY KEY (bando_id, settore)
    );

    CREATE TABLE IF NOT EXISTS bandi_destinatari (
        bando_id        TEXT NOT NULL REFERENCES bandi(id) ON DELETE CASCADE,
        destinatario    TEXT NOT NULL,
        PRIMARY KEY (bando_id, destinatario)
    );

    -- ─────────────────────────────────────────
    -- ENTITÀ (aziende, università, ricercatori)
    -- ─────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS entita (
        id              TEXT PRIMARY KEY,
        tipo            TEXT NOT NULL,   -- azienda | università | ente_ricerca | ricercatore
        nome            TEXT NOT NULL,
        piva            TEXT,
        ateco           TEXT,
        dimensione      TEXT,            -- micro | piccola | media | grande
        sede_citta      TEXT,
        sede_regione    TEXT,
        paese           TEXT DEFAULT 'IT',
        sito_web        TEXT,
        email           TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        updated_at      TEXT DEFAULT (datetime('now'))
    );

    -- Segnali di interesse per entità (CPV storici, topic CORDIS, keywords job, brevetti, ecc.)
    CREATE TABLE IF NOT EXISTS segnali (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        entita_id       TEXT NOT NULL REFERENCES entita(id) ON DELETE CASCADE,
        tipo            TEXT NOT NULL,
        -- cpv_vinto | cordis_topic | brevetto_cpc | job_keyword
        -- openalex_concept | orcid_keyword | news_topic | sito_keyword
        valore          TEXT NOT NULL,
        peso            REAL DEFAULT 1.0,
        fonte           TEXT,
        data_rilevazione TEXT,
        raw             TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_segnali_entita ON segnali(entita_id);
    CREATE INDEX IF NOT EXISTS idx_segnali_tipo   ON segnali(tipo);

    CREATE TABLE IF NOT EXISTS contratti_vinti (
        id              TEXT PRIMARY KEY,
        entita_id       TEXT REFERENCES entita(id),
        cpv             TEXT,
        importo         REAL,
        ente_appaltante TEXT,
        anno            INTEGER,
        fonte           TEXT
    );

    CREATE TABLE IF NOT EXISTS pubblicazioni (
        id              TEXT PRIMARY KEY,
        entita_id       TEXT REFERENCES entita(id),
        titolo          TEXT,
        anno            INTEGER,
        concetti_json   TEXT,   -- JSON array concetti OpenAlex
        doi             TEXT,
        fonte           TEXT,
        openalex_id     TEXT
    );

    -- ─────────────────────────────────────────
    -- MATCHING
    -- ─────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS match_scores (
        bando_id        TEXT NOT NULL REFERENCES bandi(id),
        entita_id       TEXT NOT NULL REFERENCES entita(id),
        score           REAL NOT NULL,
        dettaglio_json  TEXT,
        calcolato_at    TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (bando_id, entita_id)
    );
    CREATE INDEX IF NOT EXISTS idx_match_score ON match_scores(score DESC);
    """)

    # Migrazioni idempotenti per DB esistenti (CREATE TABLE IF NOT EXISTS
    # non aggiunge colonne nuove)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bandi)").fetchall()}
    if "regione" not in cols:
        conn.execute("ALTER TABLE bandi ADD COLUMN regione TEXT")

    conn.commit()
    conn.close()
    print(f"[db] Inizializzato: {DB_PATH}")


# ── Helpers upsert ────────────────────────────────────────────────────────────

def upsert_bando(b: dict):
    """Inserisce o aggiorna un bando e le sue tabelle satellite."""
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO bandi
            (id,fonte,tipo,titolo,descrizione,ente_nome,ente_paese,regione,
             importo_min,importo_max,importo_stimato,valuta,
             data_pubblicazione,data_scadenza,stato,
             url_originale,url_pdf,raw_json,created_at,updated_at)
        VALUES
            (:id,:fonte,:tipo,:titolo,:descrizione,:ente_nome,:ente_paese,:regione,
             :importo_min,:importo_max,:importo_stimato,:valuta,
             :data_pubblicazione,:data_scadenza,:stato,
             :url_originale,:url_pdf,:raw_json,:created_at,:updated_at)
        ON CONFLICT(id) DO UPDATE SET
            titolo=excluded.titolo,
            descrizione=excluded.descrizione,
            regione=COALESCE(excluded.regione, regione),
            importo_stimato=excluded.importo_stimato,
            data_scadenza=excluded.data_scadenza,
            stato=excluded.stato,
            raw_json=excluded.raw_json,
            updated_at=excluded.updated_at
    """, {**b, "created_at": now, "updated_at": now,
          "regione": b.get("regione"),
          "raw_json": json.dumps(b.get("_raw", {}), ensure_ascii=False)})

    bid = b["id"]
    for cpv in b.get("cpv_codes", []):
        conn.execute(
            "INSERT OR IGNORE INTO bandi_cpv(bando_id,cpv_code) VALUES(?,?)",
            (bid, cpv))
    for s in b.get("settori", []):
        conn.execute(
            "INSERT OR IGNORE INTO bandi_settori(bando_id,settore) VALUES(?,?)",
            (bid, s))
    for d in b.get("destinatari", []):
        conn.execute(
            "INSERT OR IGNORE INTO bandi_destinatari(bando_id,destinatario) VALUES(?,?)",
            (bid, d))
    conn.commit()
    conn.close()


def count_bandi():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM bandi").fetchone()[0]
    conn.close()
    return n


if __name__ == "__main__":
    init_db()
