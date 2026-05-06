"""
Orchestratore matching -- calcola e mostra i match bandi -> entita.

Uso:
    python -m matching.run_matching
    python -m matching.run_matching --min-score 0.20 --top 15
    python -m matching.run_matching --show bando_id
    python -m matching.run_matching --stats
"""
import argparse
import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from matching.match_engine import compute_all_scores, DB_PATH

SEP = "-" * 70


def run_matching(min_score: float = 0.15, top_n: int = 20, verbose: bool = True) -> int:
    return compute_all_scores(min_score=min_score, top_n=top_n, verbose=verbose)


def show_matches(bando_id: str, limit: int = 10):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    bando = con.execute(
        "SELECT id, titolo, stato FROM bandi WHERE id=?", (bando_id,)
    ).fetchone()
    if not bando:
        print(f"Bando non trovato: {bando_id}")
        return

    print(f"\n{SEP}")
    print(f"  Bando: {bando['titolo'][:65]}")
    print(f"  ID:    {bando['id']}   Stato: {bando['stato']}")
    print(SEP)

    rows = con.execute(
        """SELECT ms.score, ms.dettaglio_json, e.nome, e.tipo, e.sede_regione
           FROM match_scores ms
           JOIN entita e ON e.id = ms.entita_id
           WHERE ms.bando_id = ?
           ORDER BY ms.score DESC
           LIMIT ?""",
        (bando_id, limit),
    ).fetchall()

    if not rows:
        print("  Nessun match trovato. Esegui prima: python -m matching.run_matching")
        return

    print(f"  {'#':<4} {'Score':>6}  {'Tipo':<14}  {'Regione':<14}  Nome")
    print(f"  {'-'*4} {'-'*6}  {'-'*14}  {'-'*14}  {'-'*30}")
    for i, r in enumerate(rows, 1):
        det = json.loads(r["dettaglio_json"] or "{}")
        tipo = r["tipo"] or ""
        regione = (r["sede_regione"] or "")[:14]
        nome = r["nome"][:50]
        print(f"  {i:<4} {r['score']:>6.3f}  {tipo:<14}  {regione:<14}  {nome}")

    print(f"\n  Dettaglio top match:")
    if rows:
        det = json.loads(rows[0]["dettaglio_json"] or "{}")
        print(f"  tipo={det.get('tipo',0):.2f}  settori={det.get('settori',0):.2f}"
              f"  concept={det.get('concept',0):.2f}  keyword={det.get('keyword',0):.2f}"
              f"  peso={det.get('peso',0):.2f}  geo={det.get('geo',0):.2f}")
    con.close()


def show_stats():
    con = sqlite3.connect(DB_PATH)
    print(f"\n{SEP}")
    print("  STATISTICHE MATCHING")
    print(SEP)

    n_match = con.execute("SELECT COUNT(*) FROM match_scores").fetchone()[0]
    n_bandi = con.execute(
        "SELECT COUNT(DISTINCT bando_id) FROM match_scores"
    ).fetchone()[0]
    n_entita = con.execute(
        "SELECT COUNT(DISTINCT entita_id) FROM match_scores"
    ).fetchone()[0]
    avg_score = con.execute("SELECT AVG(score) FROM match_scores").fetchone()[0] or 0

    print(f"  Match totali:          {n_match:>8}")
    print(f"  Bandi con almeno 1:    {n_bandi:>8}")
    print(f"  Entita matchate:       {n_entita:>8}")
    print(f"  Score medio:           {avg_score:>8.3f}")

    print(f"\n  Top 10 bandi per match:")
    rows = con.execute(
        """SELECT b.titolo, COUNT(*) as n, MAX(ms.score) as best
           FROM match_scores ms JOIN bandi b ON b.id=ms.bando_id
           GROUP BY ms.bando_id ORDER BY best DESC LIMIT 10"""
    ).fetchall()
    for r in rows:
        print(f"    {r[0][:50]:<50}  n={r[1]:>3}  best={r[2]:.3f}")

    print(f"\n  Top 10 entita piu' matchate:")
    rows = con.execute(
        """SELECT e.nome, e.tipo, COUNT(*) as n, MAX(ms.score) as best
           FROM match_scores ms JOIN entita e ON e.id=ms.entita_id
           GROUP BY ms.entita_id ORDER BY n DESC LIMIT 10"""
    ).fetchall()
    for r in rows:
        print(f"    {r[0][:40]:<40}  ({r[1]})  n={r[2]:>3}  best={r[3]:.3f}")

    print(f"\n  Distribuzione score:")
    brackets = [(0.7, 1.0, "0.70-1.00"), (0.5, 0.7, "0.50-0.70"),
                (0.3, 0.5, "0.30-0.50"), (0.15, 0.3, "0.15-0.30")]
    for lo, hi, label in brackets:
        n = con.execute(
            "SELECT COUNT(*) FROM match_scores WHERE score>=? AND score<?",
            (lo, hi)
        ).fetchone()[0]
        bar = "#" * (n * 40 // max(n_match, 1))
        print(f"    {label}  {n:>5}  {bar}")

    con.close()


def show_entity_bandi(entita_query: str, limit: int = 10):
    """Mostra i bandi piu' rilevanti per una specifica entita."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Cerca per nome o id
    row = con.execute(
        "SELECT id, nome, tipo FROM entita WHERE id=? OR nome LIKE ? LIMIT 1",
        (entita_query, f"%{entita_query}%"),
    ).fetchone()
    if not row:
        print(f"Entita non trovata: {entita_query}")
        return

    print(f"\n{SEP}")
    print(f"  Entita: {row['nome'][:65]}")
    print(f"  ID:     {row['id']}   Tipo: {row['tipo']}")
    print(SEP)

    rows = con.execute(
        """SELECT ms.score, ms.dettaglio_json, b.titolo, b.fonte, b.stato,
                  b.data_scadenza, b.importo_stimato
           FROM match_scores ms
           JOIN bandi b ON b.id = ms.bando_id
           WHERE ms.entita_id = ?
           ORDER BY ms.score DESC
           LIMIT ?""",
        (row["id"], limit),
    ).fetchall()

    if not rows:
        print("  Nessun match trovato. Esegui prima: python -m matching.run_matching")
        return

    print(f"  {'#':<4} {'Score':>6}  {'Fonte':<14}  {'Stato':<8}  Titolo")
    print(f"  {'-'*4} {'-'*6}  {'-'*14}  {'-'*8}  {'-'*40}")
    for i, r in enumerate(rows, 1):
        importo = f"€{r['importo_stimato']/1e6:.1f}M" if r["importo_stimato"] else ""
        scad = (r["data_scadenza"] or "")[:10]
        titolo = r["titolo"][:55] if r["titolo"] else ""
        print(f"  {i:<4} {r['score']:>6.3f}  {r['fonte']:<14}  {r['stato']:<8}  {titolo}")
        if scad or importo:
            print(f"         {'':>6}  {'':14}  {'':8}  Scadenza: {scad}  {importo}")
    con.close()


def main():
    p = argparse.ArgumentParser(description="Motore di matching bandi -> entita")
    p.add_argument("--min-score",  type=float, default=0.15)
    p.add_argument("--top",        type=int,   default=20,
                   help="Max match per bando da salvare")
    p.add_argument("--show",       type=str,   default=None,
                   help="Mostra top match per un bando (id)")
    p.add_argument("--for-entity", type=str,   default=None,
                   help="Mostra bandi piu' rilevanti per una entita (nome o id)")
    p.add_argument("--stats",      action="store_true")
    p.add_argument("--quiet",      action="store_true")
    args = p.parse_args()

    if args.stats:
        show_stats()
    elif args.show:
        show_matches(args.show, limit=args.top)
    elif args.for_entity:
        show_entity_bandi(args.for_entity, limit=args.top)
    else:
        n = run_matching(
            min_score=args.min_score,
            top_n=args.top,
            verbose=not args.quiet,
        )
        show_stats()


if __name__ == "__main__":
    main()
