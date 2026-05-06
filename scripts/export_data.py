"""
Esporta i dati raccolti e i matching del DB in formati condivisibili.

Output in data/exports/:
  - bandi.csv       (333 record)
  - entita.csv      (307 record)
  - segnali.csv     (2.392 record)
  - matches.csv     (5.320 record con breakdown 6 componenti)
  - summary.json    (statistiche aggregate)

Tutti i CSV sono UTF-8 con BOM (Excel italiano li apre senza problemi),
separatore virgola, quoting minimal.
"""
import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db" / "bandi.db"
EXPORT_DIR = ROOT / "data" / "exports"


def open_csv(path: Path):
    """Apre un file CSV pronto per Excel italiano (BOM UTF-8)."""
    f = open(path, "w", encoding="utf-8-sig", newline="")
    return f, csv.writer(f, quoting=csv.QUOTE_MINIMAL)


def export_bandi(conn) -> int:
    path = EXPORT_DIR / "bandi.csv"
    f, w = open_csv(path)
    w.writerow([
        "id", "fonte", "tipo", "titolo", "descrizione",
        "ente_nome", "ente_paese", "regione",
        "importo_min", "importo_max", "importo_stimato", "valuta",
        "data_pubblicazione", "data_scadenza", "stato",
        "url_originale", "url_pdf", "settori", "destinatari", "cpv_codes",
    ])
    rows = conn.execute(
        "SELECT * FROM bandi ORDER BY fonte, data_pubblicazione DESC"
    ).fetchall()
    n = 0
    for b in rows:
        settori = [r[0] for r in conn.execute(
            "SELECT settore FROM bandi_settori WHERE bando_id=?",
            (b["id"],)).fetchall()]
        destinatari = [r[0] for r in conn.execute(
            "SELECT destinatario FROM bandi_destinatari WHERE bando_id=?",
            (b["id"],)).fetchall()]
        cpv = [r[0] for r in conn.execute(
            "SELECT cpv_code FROM bandi_cpv WHERE bando_id=?",
            (b["id"],)).fetchall()]
        w.writerow([
            b["id"], b["fonte"], b["tipo"], b["titolo"],
            (b["descrizione"] or "")[:1000],
            b["ente_nome"], b["ente_paese"], b["regione"],
            b["importo_min"], b["importo_max"], b["importo_stimato"],
            b["valuta"], b["data_pubblicazione"], b["data_scadenza"],
            b["stato"], b["url_originale"], b["url_pdf"],
            "|".join(settori),
            "|".join(destinatari),
            "|".join(cpv),
        ])
        n += 1
    f.close()
    print(f"  bandi.csv:    {n:>5} record  -> {path.name}")
    return n


def export_entita(conn) -> int:
    path = EXPORT_DIR / "entita.csv"
    f, w = open_csv(path)
    w.writerow([
        "id", "tipo", "nome", "piva", "ateco", "dimensione",
        "sede_citta", "sede_regione", "paese",
        "sito_web", "email", "n_segnali",
    ])
    rows = conn.execute(
        "SELECT e.*, (SELECT COUNT(*) FROM segnali s WHERE s.entita_id=e.id) "
        "AS n_segnali FROM entita e ORDER BY e.tipo, e.nome"
    ).fetchall()
    n = 0
    for e in rows:
        w.writerow([
            e["id"], e["tipo"], e["nome"], e["piva"], e["ateco"],
            e["dimensione"], e["sede_citta"], e["sede_regione"], e["paese"],
            e["sito_web"], e["email"], e["n_segnali"],
        ])
        n += 1
    f.close()
    print(f"  entita.csv:   {n:>5} record  -> {path.name}")
    return n


def export_segnali(conn) -> int:
    path = EXPORT_DIR / "segnali.csv"
    f, w = open_csv(path)
    w.writerow([
        "entita_id", "entita_nome", "entita_tipo",
        "tipo_segnale", "valore", "peso", "fonte",
    ])
    rows = conn.execute(
        "SELECT s.entita_id, e.nome AS entita_nome, e.tipo AS entita_tipo, "
        "       s.tipo, s.valore, s.peso, s.fonte "
        "FROM segnali s JOIN entita e ON e.id = s.entita_id "
        "ORDER BY e.tipo, e.nome, s.tipo"
    ).fetchall()
    n = 0
    for r in rows:
        w.writerow([
            r["entita_id"], r["entita_nome"], r["entita_tipo"],
            r["tipo"], (r["valore"] or "")[:500], r["peso"], r["fonte"],
        ])
        n += 1
    f.close()
    print(f"  segnali.csv:  {n:>5} record  -> {path.name}")
    return n


def export_matches(conn) -> int:
    path = EXPORT_DIR / "matches.csv"
    f, w = open_csv(path)
    w.writerow([
        # Bando
        "bando_id", "bando_fonte", "bando_titolo", "bando_regione",
        "bando_stato", "bando_data_scadenza", "bando_importo_stimato",
        # Entita
        "entita_id", "entita_tipo", "entita_nome", "entita_sede_regione",
        # Match score
        "score",
        # Breakdown 6 componenti
        "score_tipo", "score_settori", "score_concept",
        "score_keyword", "score_peso", "score_geo",
    ])
    rows = conn.execute(
        """SELECT ms.bando_id, ms.entita_id, ms.score, ms.dettaglio_json,
                  b.fonte AS bando_fonte, b.titolo AS bando_titolo,
                  b.regione AS bando_regione, b.stato AS bando_stato,
                  b.data_scadenza, b.importo_stimato,
                  e.tipo AS entita_tipo, e.nome AS entita_nome,
                  e.sede_regione AS entita_sede
           FROM match_scores ms
           JOIN bandi b ON b.id = ms.bando_id
           JOIN entita e ON e.id = ms.entita_id
           ORDER BY ms.bando_id, ms.score DESC"""
    ).fetchall()
    n = 0
    for r in rows:
        det = json.loads(r["dettaglio_json"] or "{}")
        w.writerow([
            r["bando_id"], r["bando_fonte"],
            (r["bando_titolo"] or "")[:200],
            r["bando_regione"], r["bando_stato"],
            r["data_scadenza"], r["importo_stimato"],
            r["entita_id"], r["entita_tipo"], r["entita_nome"],
            r["entita_sede"],
            f"{r['score']:.4f}",
            f"{det.get('tipo', 0):.3f}",
            f"{det.get('settori', 0):.3f}",
            f"{det.get('concept', 0):.3f}",
            f"{det.get('keyword', 0):.3f}",
            f"{det.get('peso', 0):.3f}",
            f"{det.get('geo', 0):.3f}",
        ])
        n += 1
    f.close()
    print(f"  matches.csv:  {n:>5} record  -> {path.name}")
    return n


def export_summary(conn, counts: dict) -> Path:
    path = EXPORT_DIR / "summary.json"
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "totals": counts,
        "bandi_per_fonte_stato": [
            dict(r) for r in conn.execute(
                "SELECT fonte, stato, COUNT(*) AS n FROM bandi "
                "GROUP BY fonte, stato ORDER BY fonte, stato").fetchall()
        ],
        "entita_per_tipo": [
            dict(r) for r in conn.execute(
                "SELECT tipo, COUNT(*) AS n FROM entita "
                "GROUP BY tipo ORDER BY n DESC").fetchall()
        ],
        "segnali_per_tipo": [
            dict(r) for r in conn.execute(
                "SELECT tipo, COUNT(*) AS n FROM segnali "
                "GROUP BY tipo ORDER BY n DESC").fetchall()
        ],
        "score_distribution": [
            {"bracket": label, "n": conn.execute(
                "SELECT COUNT(*) FROM match_scores WHERE score>=? AND score<?",
                (lo, hi)).fetchone()[0]}
            for lo, hi, label in [
                (0.7, 1.01, "0.70+"),
                (0.5, 0.7,  "0.50-0.70"),
                (0.3, 0.5,  "0.30-0.50"),
                (0.15, 0.3, "0.15-0.30"),
            ]
        ],
        "geo_coverage": {
            "bandi_con_regione": conn.execute(
                "SELECT COUNT(*) FROM bandi WHERE regione IS NOT NULL"
                ).fetchone()[0],
            "bandi_totali": counts["bandi"],
            "entita_con_sede": conn.execute(
                "SELECT COUNT(*) FROM entita WHERE sede_regione IS NOT NULL"
                ).fetchone()[0],
            "entita_totali": counts["entita"],
        },
        "matcher_weights": {
            "tipo": 0.30, "settori": 0.20, "concept": 0.15,
            "keyword": 0.10, "peso": 0.15, "geo": 0.10,
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"  summary.json: {len(summary)} top-level keys -> {path.name}")
    return path


def main():
    if not DB_PATH.exists():
        print(f"[Export] DB non trovato: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[Export] Output dir: {EXPORT_DIR}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("bandi", "entita", "segnali", "match_scores")
    }

    print("[Export] Scrittura file CSV/JSON:")
    n_b = export_bandi(conn)
    n_e = export_entita(conn)
    n_s = export_segnali(conn)
    n_m = export_matches(conn)
    export_summary(conn, counts)

    conn.close()

    total_size = sum(
        f.stat().st_size for f in EXPORT_DIR.iterdir() if f.is_file()
    )
    print(f"[Export] Completato. {n_b + n_e + n_s + n_m + 1} record totali, "
          f"{total_size / 1024:.1f} KB su disco.")


if __name__ == "__main__":
    main()
