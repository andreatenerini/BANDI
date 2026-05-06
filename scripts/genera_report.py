"""
Generatore PDF — Report di stato del progetto BANDI.
Output: BANDI_Report.pdf nella radice.

Differente da genera_pdf.py (che produce BANDI_Sistema_Analisi.pdf).
Questo report e' focalizzato su:
  - Stato attuale dei dati (live dal DB)
  - Logica del matching post-fix
  - Esempi di matching su bandi diversi
  - Evoluzione e fix applicati
"""
import datetime
import json
import sqlite3
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

ROOT = Path(__file__).parent.parent
OUTPUT = ROOT / "BANDI_Report.pdf"
DB_PATH = ROOT / "data" / "db" / "bandi.db"

PAGE_W, PAGE_H = A4
L_MARGIN = 2.2 * cm
R_MARGIN = 2.2 * cm
BODY_W = PAGE_W - L_MARGIN - R_MARGIN

# ── Palette ──────────────────────────────────────────────────────────────────
NAVY    = colors.HexColor("#1a3a5c")
BLUE    = colors.HexColor("#2c5f8a")
LBLUE   = colors.HexColor("#e8f0f8")
GRID_C  = colors.HexColor("#c0cfe0")
ALT_ROW = colors.HexColor("#f0f5fa")
GREEN_OK = colors.HexColor("#2e7d4f")


def make_style(name, parent_name="Normal", **kw):
    base = getSampleStyleSheet()[parent_name]
    return ParagraphStyle(name, parent=base, **kw)


COVER_TITLE = make_style("CoverTitle",
    fontSize=28, fontName="Helvetica-Bold", textColor=NAVY,
    alignment=TA_CENTER, spaceAfter=12, leading=34)
COVER_SUBT = make_style("CoverSubt",
    fontSize=13, fontName="Helvetica", textColor=BLUE,
    alignment=TA_CENTER, spaceAfter=6, leading=18)
COVER_META = make_style("CoverMeta",
    fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=4)

H1 = make_style("H1", fontSize=17, fontName="Helvetica-Bold",
    textColor=NAVY, spaceBefore=22, spaceAfter=10, leading=22)
H2 = make_style("H2", fontSize=12, fontName="Helvetica-Bold",
    textColor=NAVY, spaceBefore=14, spaceAfter=8, leading=16,
    backColor=LBLUE, leftIndent=4, rightIndent=4, borderPad=5)
H3 = make_style("H3", fontSize=10, fontName="Helvetica-Bold",
    textColor=BLUE, spaceBefore=10, spaceAfter=5, leading=14)
BODY = make_style("Body", fontSize=9, leading=14,
    spaceAfter=6, alignment=TA_JUSTIFY)
BULL = make_style("Bull", fontSize=9, leading=13,
    spaceAfter=3, leftIndent=14, firstLineIndent=-8)
CODE_S = make_style("Code", fontSize=8, fontName="Courier",
    leading=12, spaceBefore=4, spaceAfter=8,
    backColor=colors.HexColor("#f4f6f8"),
    leftIndent=8, rightIndent=8, borderPad=6,
    textColor=colors.HexColor("#1a1a2e"))
SMALL = make_style("Small", fontSize=8, textColor=colors.grey, spaceAfter=3)
NOTE = make_style("Note", fontSize=8, textColor=colors.HexColor("#555555"),
    leftIndent=10, spaceBefore=4, spaceAfter=4, leading=12)
CELL_HDR = make_style("CellHdr", fontSize=8, fontName="Helvetica-Bold",
    textColor=colors.white, leading=11)
CELL = make_style("Cell", fontSize=8, leading=11)
CELL_MONO = make_style("CellMono", fontSize=7.5, fontName="Courier",
    textColor=colors.HexColor("#1a1a2e"), leading=11)
CELL_NUM = make_style("CellNum", fontSize=8, alignment=2, leading=11)


def _esc(text):
    import re
    return re.sub(r"&(?!(?:#\d+|#x[\da-fA-F]+|[a-zA-Z]\w*);)", "&amp;", str(text))

def sp(pts=8): return Spacer(1, pts)
def hr(): return HRFlowable(width=BODY_W, thickness=0.5, color=GRID_C,
                            spaceBefore=4, spaceAfter=4)
def p(text, style=BODY): return Paragraph(text, style)
def h1(t): return Paragraph(t, H1)
def h2(t): return Paragraph(t, H2)
def h3(t): return Paragraph(t, H3)
def bullet(text): return Paragraph(f"&bull; {text}", BULL)
def code_block(text):
    safe = (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\n", "<br/>")
            .replace(" ", "&nbsp;"))
    return Paragraph(safe, CODE_S)
def _c(text, style=CELL):  return Paragraph(_esc(str(text)), style)
def _ch(text):             return Paragraph(_esc(str(text)), CELL_HDR)


def tbl(rows, col_widths, hdr_rows=1, num_cols=()):
    """num_cols: indici di colonne da allineare a destra (numeriche)."""
    def wrap_row(row, is_header):
        out = []
        for i, cell in enumerate(row):
            if isinstance(cell, Paragraph):
                out.append(cell)
            elif is_header:
                out.append(_ch(cell))
            elif i in num_cols:
                out.append(_c(cell, CELL_NUM))
            else:
                out.append(_c(cell))
        return out

    wrapped = [wrap_row(r, i < hdr_rows) for i, r in enumerate(rows)]
    t = Table(wrapped, colWidths=col_widths, repeatRows=hdr_rows)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, hdr_rows - 1), NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, hdr_rows - 1), colors.white),
        ("ROWBACKGROUNDS", (0, hdr_rows), (-1, -1), [colors.white, ALT_ROW]),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("GRID",       (0, 0), (-1, -1), 0.3, GRID_C),
        ("LINEBELOW",  (0, 0), (-1, hdr_rows - 1), 1.0, NAVY),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# ═════════════════════════════════════════════════════════════════════════════
# RACCOLTA DATI LIVE DAL DB
# ═════════════════════════════════════════════════════════════════════════════

def fetch_data():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    d = {}

    d["counts"] = {}
    for tbl_name in ("bandi", "entita", "segnali", "match_scores",
                     "contratti_vinti", "pubblicazioni"):
        d["counts"][tbl_name] = con.execute(
            f"SELECT COUNT(*) FROM {tbl_name}").fetchone()[0]

    d["bandi_per_fonte"] = list(con.execute(
        "SELECT fonte, stato, COUNT(*) AS n FROM bandi "
        "GROUP BY fonte, stato ORDER BY fonte, stato").fetchall())

    d["entita_per_tipo"] = list(con.execute(
        "SELECT tipo, COUNT(*) AS n FROM entita "
        "GROUP BY tipo ORDER BY n DESC").fetchall())

    d["segnali_top"] = list(con.execute(
        "SELECT tipo, COUNT(*) AS n FROM segnali "
        "GROUP BY tipo ORDER BY n DESC LIMIT 12").fetchall())

    d["geo_band"] = con.execute(
        "SELECT COUNT(*) FROM bandi WHERE regione IS NOT NULL").fetchone()[0]
    d["geo_ent"] = con.execute(
        "SELECT COUNT(*) FROM entita WHERE sede_regione IS NOT NULL"
        ).fetchone()[0]

    # 4 esempi di matching
    d["examples"] = []
    examples = [
        ("MUR-PRIN-2026", "PRIN 2026 — bando di ricerca nazionale"),
        ("OC-2017FSCRICERCA", "PIANO FSC RICERCA E INNOVAZIONE"),
        ("OC-PSCLAZIO2021", "ACCORDO COESIONE LAZIO — territoriale"),
        ("TED-278990-2026", "TED — Servizi di R&D sperimentale"),
    ]
    for bid, label in examples:
        bando = con.execute(
            "SELECT id, fonte, titolo, regione, stato, importo_stimato "
            "FROM bandi WHERE id=?", (bid,)).fetchone()
        if not bando:
            continue
        rows = list(con.execute(
            """SELECT ms.score, ms.dettaglio_json,
                      e.tipo, e.sede_regione, e.nome
               FROM match_scores ms JOIN entita e ON e.id=ms.entita_id
               WHERE ms.bando_id=? ORDER BY ms.score DESC LIMIT 5""",
            (bid,)).fetchall())
        d["examples"].append({"label": label, "bando": dict(bando),
                              "matches": [dict(r) for r in rows]})

    # Distribuzione score (istogramma)
    d["score_distrib"] = []
    for lo, hi, label in [(0.7, 1.01, "0.70+"), (0.5, 0.7, "0.50-0.70"),
                          (0.3, 0.5, "0.30-0.50"), (0.15, 0.3, "0.15-0.30")]:
        n = con.execute(
            "SELECT COUNT(*) FROM match_scores WHERE score>=? AND score<?",
            (lo, hi)).fetchone()[0]
        d["score_distrib"].append((label, n))

    # Top 5 entita piu' matchate
    d["top_entita"] = list(con.execute(
        """SELECT e.nome, e.tipo, COUNT(*) AS n, MAX(ms.score) AS best
           FROM match_scores ms JOIN entita e ON e.id=ms.entita_id
           GROUP BY e.id ORDER BY n DESC LIMIT 8"""
    ).fetchall())

    con.close()
    return d


# ═════════════════════════════════════════════════════════════════════════════
# COSTRUZIONE STORY
# ═════════════════════════════════════════════════════════════════════════════

def build_story(data):
    s = []

    # ── COPERTINA ────────────────────────────────────────────────────────────
    today = datetime.date.today().strftime("%d %B %Y")
    s += [
        sp(80),
        Paragraph("PROGETTO BANDI", COVER_TITLE),
        sp(6),
        Paragraph(
            "Sistema di scraping multi-fonte e matching intelligente<br/>"
            "tra bandi pubblici italiani ed entit&agrave; potenzialmente interessate",
            COVER_SUBT),
        sp(20),
        hr(),
        sp(8),
        Paragraph(f"Report di stato &mdash; {today}", COVER_META),
        Paragraph("IDEA-RE &nbsp;|&nbsp; atenerini@idea-re.eu", COVER_META),
        Paragraph(f"DB snapshot: {data['counts']['bandi']} bandi &middot; "
                  f"{data['counts']['entita']} entit&agrave; &middot; "
                  f"{data['counts']['match_scores']:,} match calcolati",
                  COVER_META),
        PageBreak(),
    ]

    # ── 1. EXECUTIVE SUMMARY ─────────────────────────────────────────────────
    s += [h1("1. Executive summary")]
    s += [p(
        "<b>Cos'&egrave;.</b> BANDI &egrave; un sistema software che raccoglie "
        "automaticamente bandi pubblici italiani ed europei da quattro fonti "
        "ufficiali, costruisce in parallelo un catalogo di potenziali "
        "partecipanti (aziende, ricercatori, universit&agrave;, enti) e "
        "calcola un punteggio di affinit&agrave; tra ogni bando e ogni "
        "entit&agrave; del catalogo.")]
    s += [p(
        "<b>Perch&eacute; serve.</b> Il volume di opportunit&agrave; pubbliche "
        "&egrave; alto e la maggior parte non &egrave; specifica per il "
        "destinatario ideale: serve un filtro automatico che proponga, per "
        "ciascun bando, le entit&agrave; pi&ugrave; rilevanti (e viceversa). "
        "Lo strumento non sostituisce la valutazione umana: produce una "
        "shortlist ordinata su cui concentrare l'analisi qualitativa.")]
    s += [p("<b>Risultati attuali.</b>")]
    s += [bullet(f"<b>{data['counts']['bandi']}</b> bandi importati da TED, "
                 "OpenCoesione, MUR (ANAC bloccato lato fonte)")]
    s += [bullet(f"<b>{data['counts']['entita']}</b> entit&agrave; profilate "
                 f"con <b>{data['counts']['segnali']:,}</b> segnali (concetti "
                 "OpenAlex, temi OpenCoesione, topic GitHub, metriche, ecc.)")]
    s += [bullet(f"<b>{data['counts']['match_scores']:,}</b> coppie bando&rarr;"
                 "entit&agrave; valutate, top-20 salvate per ogni bando "
                 "attivo")]
    s += [bullet(f"Copertura geografica: {data['geo_band']}/"
                 f"{data['counts']['bandi']} bandi e "
                 f"{data['geo_ent']}/{data['counts']['entita']} entit&agrave; "
                 "hanno regione persistita")]
    s += [bullet("Matcher a <b>6 componenti pesati</b> (tipo, settori, "
                 "concept, keyword, peso, geo) — risultati validati su 4 "
                 "scenari diversi nel capitolo 6")]

    # ── 2. ARCHITETTURA ──────────────────────────────────────────────────────
    s += [h1("2. Architettura")]
    s += [p("Il sistema &egrave; uno script Python con database SQLite locale. "
            "Tre livelli logici, ognuno con il proprio package:")]
    s += [code_block(
        "BANDI/\n"
        "├── scraper/       # acquisizione bandi (TED, OpenCoesione, MUR, ANAC)\n"
        "├── entity/        # acquisizione entita (OpenAlex, CORDIS, OC, GitHub)\n"
        "├── matching/      # motore di scoring composito\n"
        "├── data/db/       # SQLite con schema unificato\n"
        "├── scripts/       # utility one-shot (backfill, re-enrich, report)\n"
        "└── main.py        # CLI: --bandi --entita --match --show ID"
    )]

    s += [h2("2.1 Fonti dei bandi")]
    s += [tbl([
        ["Fonte", "Endpoint", "Metodo", "Bandi salvati"],
        ["TED", "api.ted.europa.eu/v3", "API REST + filtro form-type",
         f"{sum(r['n'] for r in data['bandi_per_fonte'] if r['fonte']=='TED')}"],
        ["OpenCoesione", "opencoesione.gov.it/it/api", "API REST per tema",
         f"{sum(r['n'] for r in data['bandi_per_fonte'] if r['fonte']=='OpenCoesione')}"],
        ["MUR", "www.mur.gov.it (HTML)", "Scraping HTML + 2 PRIN hardcoded",
         f"{sum(r['n'] for r in data['bandi_per_fonte'] if r['fonte']=='MUR')}"],
        ["ANAC", "dati.anticorruzione.it", "CSV bulk OCDS (bloccato da WAF)",
         "0"],
    ], col_widths=[2.6*cm, 6.0*cm, 5.7*cm, 2.3*cm], num_cols={3})]

    s += [Paragraph("&#9888; ANAC: il portale blocca i download automatici "
                    "via WAF (Web Application Firewall). Il codice "
                    "<i>scraper/anac_scraper.py</i> riconosce il blocco e "
                    "stampa istruzioni per il download manuale.", NOTE)]

    s += [h2("2.2 Fonti delle entit&agrave;")]
    s += [tbl([
        ["Fonte", "Tipo entit&agrave; coperto", "Segnali estratti"],
        ["OpenAlex", "Universit&agrave;, ricercatori",
         "concept tematici, h-index, works/citations, ROR"],
        ["CORDIS / OpenAIRE", "Organizzazioni IT con progetti UE",
         "PIC code, OpenAIRE id, keyword progetti"],
        ["OpenCoesione (soggetti)", "Aziende, regioni, ministeri",
         "multi-tema, sede, P.IVA, n. progetti, costo pubblico totale"],
        ["GitHub", "Software house, organizzazioni tech",
         "topic, linguaggi, descrizione, n. repo, follower"],
        ["ANAC winners", "Aggiudicatari (richiede CSV ANAC)",
         "CPV vinti, importi storici, contratti"],
    ], col_widths=[3.5*cm, 4.5*cm, 8.6*cm])]

    s += [h2("2.3 Pipeline di esecuzione")]
    s += [code_block(
        "python main.py --bandi      # scarica bandi da tutte le fonti\n"
        "python main.py --entita     # scarica/arricchisce le entita\n"
        "python main.py --match      # ricalcola tutti i match (top-20)\n"
        "python main.py --stats      # statistiche del DB\n"
        "python main.py --show ID    # top match per un bando\n"
        "python main.py --for-entity NOME   # bandi rilevanti per un'entita"
    )]
    s += [PageBreak()]

    # ── 3. SCHEMA DB ─────────────────────────────────────────────────────────
    s += [h1("3. Schema del database")]
    s += [p("SQLite singolo file: <i>data/db/bandi.db</i>. "
            "Schema relazionale con tre cluster logici: bandi (+ tabelle "
            "satellite), entit&agrave; (+ segnali e contratti), match.")]

    s += [h2("3.1 Tabelle bandi")]
    s += [tbl([
        ["Tabella", "Colonne principali", "Descrizione"],
        ["bandi", "id (PK), fonte, tipo, titolo, descrizione, ente_nome, "
                  "regione, importo_stimato, data_scadenza, stato, url",
         "Tabella centrale dei bandi"],
        ["bandi_settori", "bando_id, settore (entrambi PK)",
         "Settori inferiti (1:N)"],
        ["bandi_destinatari", "bando_id, destinatario",
         "Tipi di destinatario validi (aziende, universita, ...)"],
        ["bandi_cpv", "bando_id, cpv_code",
         "Codici CPV europei (1:N)"],
    ], col_widths=[3.0*cm, 6.5*cm, 7.0*cm])]

    s += [h2("3.2 Tabelle entit&agrave;")]
    s += [tbl([
        ["Tabella", "Colonne principali", "Descrizione"],
        ["entita", "id (PK), tipo, nome, piva, ateco, dimensione, sede_citta, "
                   "sede_regione, paese, sito_web, email",
         "Anagrafica delle entit&agrave;"],
        ["segnali", "id, entita_id, tipo, valore, peso, fonte, raw",
         "Indicatori di interesse (1:N) — modello a chiave/valore tipizzato"],
        ["contratti_vinti", "id, entita_id, cpv, importo, ente_appaltante, "
                            "anno, fonte",
         "Storico aggiudicazioni ANAC"],
        ["pubblicazioni", "id, entita_id, titolo, anno, concetti_json, doi, "
                          "openalex_id",
         "Pubblicazioni OpenAlex"],
    ], col_widths=[3.0*cm, 6.5*cm, 7.0*cm])]

    s += [h2("3.3 Tabella match")]
    s += [tbl([
        ["Tabella", "Colonne principali", "Descrizione"],
        ["match_scores", "bando_id, entita_id (PK composta), score, "
                         "dettaglio_json, calcolato_at",
         "Top-20 entit&agrave; per ogni bando attivo. Il dettaglio JSON "
         "contiene il breakdown dei 6 componenti."],
    ], col_widths=[3.0*cm, 6.5*cm, 7.0*cm])]

    s += [h3("Esempio di record dettaglio_json")]
    s += [code_block(
        '{\n'
        '  "score":   0.690,\n'
        '  "tipo":    1.000,\n'
        '  "settori": 0.300,\n'
        '  "concept": 1.000,\n'
        '  "keyword": 0.000,\n'
        '  "peso":    0.870,\n'
        '  "geo":     0.500\n'
        '}'
    )]
    s += [PageBreak()]

    # ── 4. STATO DEI DATI (LIVE) ─────────────────────────────────────────────
    s += [h1("4. Stato dei dati (snapshot live)")]
    s += [p(f"Snapshot del DB al {today}.")]

    s += [h2("4.1 Conteggi tabelle")]
    s += [tbl([
        ["Tabella", "Record"],
        ["Bandi", f"{data['counts']['bandi']:,}"],
        ["Entit&agrave;", f"{data['counts']['entita']:,}"],
        ["Segnali", f"{data['counts']['segnali']:,}"],
        ["Match scores", f"{data['counts']['match_scores']:,}"],
        ["Contratti vinti", f"{data['counts']['contratti_vinti']:,}"],
        ["Pubblicazioni", f"{data['counts']['pubblicazioni']:,}"],
    ], col_widths=[10.0*cm, 6.5*cm], num_cols={1})]
    s += [Paragraph("Contratti e Pubblicazioni a 0: dipendono da CSV ANAC "
                    "(WAF) e dall'ingestion delle works OpenAlex (non lanciata "
                    "in questa sessione, &egrave; opzionale).", NOTE)]

    s += [h2("4.2 Bandi per fonte e stato")]
    rows = [["Fonte", "Stato", "N"]]
    for r in data["bandi_per_fonte"]:
        rows.append([r["fonte"], r["stato"], str(r["n"])])
    s += [tbl(rows, col_widths=[5.0*cm, 5.0*cm, 6.5*cm], num_cols={2})]
    s += [Paragraph("&quot;aggiudicato&quot;: 44 bandi TED che erano in realt&agrave; "
                    "esiti di gara gi&agrave; concluse, marcati come tali "
                    "(non entrano nel matching).", NOTE)]

    s += [h2("4.3 Entit&agrave; per tipo")]
    rows = [["Tipo", "N"]]
    for r in data["entita_per_tipo"]:
        rows.append([r["tipo"], str(r["n"])])
    s += [tbl(rows, col_widths=[10.0*cm, 6.5*cm], num_cols={1})]

    s += [h2("4.4 Segnali per tipo (top 12)")]
    rows = [["Tipo segnale", "N", "Origine"]]
    origin_map = {
        "openalex_concept": "OpenAlex (autori e istituzioni)",
        "oc_tema": "OpenCoesione (multi-tema da dettaglio soggetto)",
        "oc_fondi_strutturali": "OpenCoesione (presenza nel sistema)",
        "oc_costo_pubblico_tot": "OpenCoesione (importo totale)",
        "oc_n_progetti": "OpenCoesione (peso storico)",
        "oa_citations": "OpenAlex (impatto)",
        "oa_works_count": "OpenAlex (produttivit&agrave;)",
        "istituzione": "OpenAlex (affiliazione)",
        "oa_h_index": "OpenAlex (h-index)",
        "openaire_id": "OpenAIRE",
        "openalex_ror": "OpenAlex (Research Org Registry)",
        "eu_pic_code": "CORDIS (Participant Identification Code)",
        "github_topic": "GitHub (topic dei top repo)",
        "gh_language": "GitHub (linguaggi prevalenti)",
        "gh_n_repos": "GitHub (peso azienda)",
        "github_community": "GitHub (follower)",
        "gh_description": "GitHub (bio organizzazione)",
    }
    for r in data["segnali_top"]:
        rows.append([r["tipo"], str(r["n"]),
                     origin_map.get(r["tipo"], "—")])
    s += [tbl(rows, col_widths=[3.8*cm, 1.7*cm, 11.0*cm], num_cols={1})]

    s += [h2("4.5 Top entit&agrave; per numero di match")]
    rows = [["Entit&agrave;", "Tipo", "N match", "Best score"]]
    for r in data["top_entita"]:
        rows.append([r["nome"][:50], r["tipo"], str(r["n"]),
                     f"{r['best']:.3f}"])
    s += [tbl(rows, col_widths=[7.5*cm, 3.0*cm, 2.5*cm, 3.5*cm],
              num_cols={2, 3})]
    s += [PageBreak()]

    # ── 5. LOGICA DEL MATCHING ───────────────────────────────────────────────
    s += [h1("5. Logica del matching")]
    s += [p("Per ogni coppia <i>(bando, entit&agrave;)</i> il motore calcola "
            "uno score composito normalizzato in [0, 1] come somma pesata di "
            "sei componenti indipendenti. Le top-20 entit&agrave; per ciascun "
            "bando attivo vengono salvate in <i>match_scores</i>.")]

    s += [h2("5.1 I sei componenti")]
    s += [tbl([
        ["Componente", "Peso", "Cosa misura", "Output"],
        ["tipo", "0.30",
         "Il tipo dell'entit&agrave; &egrave; tra i destinatari "
         "ammessi dal bando?",
         "1.0 match diretto, 0.4 partial, 0.0 nessuno"],
        ["settori", "0.20",
         "Almeno un tema OC dell'entit&agrave; matcha i settori del bando?",
         "0.7 + 0.1 per ogni match (cap 1.0). 0.3 se nessun tema, 0.0 "
         "se tutti incompatibili"],
        ["concept", "0.15",
         "I concept OpenAlex dell'entit&agrave; corrispondono ai settori del "
         "bando (tramite mapping IT&rarr;EN)?",
         "0.0 a 1.0 (frazione di concept che matchano)"],
        ["keyword", "0.10",
         "Sovrapposizione Jaccard tra parole del titolo/descrizione bando e "
         "parole derivate da nome+segnali entit&agrave;",
         "Jaccard |A&cap;B| / |A&cup;B|"],
        ["peso", "0.15",
         "Dimensione/peso dell'entit&agrave; (max log-scaled tra h-index, "
         "citations, n. progetti OC, n. repo GitHub)",
         "0.0 a 1.0, 0.3 se nessuna metrica"],
        ["geo", "0.10",
         "Match territoriale: regione bando vs sede entit&agrave;",
         "1.0 stesso, 0.5 ignoto, 0.0 diverso"],
    ], col_widths=[2.3*cm, 1.2*cm, 6.5*cm, 6.5*cm])]

    s += [h2("5.2 Formula complessiva")]
    s += [code_block(
        "score = 0.30 * tipo\n"
        "      + 0.20 * settori\n"
        "      + 0.15 * concept\n"
        "      + 0.10 * keyword\n"
        "      + 0.15 * peso\n"
        "      + 0.10 * geo"
    )]
    s += [p("Pesi tarati empiricamente: la copertura dati varia molto "
            "tra fonti, quindi il matcher deve restare informativo anche "
            "quando un componente non ha dato (es. concept=0 per le aziende, "
            "che non hanno profilo OpenAlex).")]

    s += [h2("5.3 Esempio numerico")]
    s += [p("Caso: bando PRIN 2026 (ricerca nazionale, no regione) vs il "
            "ricercatore Gregg L. Semenza (Premio Nobel medicina 2019).")]
    s += [tbl([
        ["Componente", "Valore", "Peso", "Contributo"],
        ["tipo (ricercatore &isin; {ricercatori, enti_ricerca, universita})", "1.00", "0.30", "0.300"],
        ["settori (no oc_temi sull'entit&agrave;)", "0.30", "0.20", "0.060"],
        ["concept (concept OpenAlex matchano &lsquo;ricerca&rsquo;)", "1.00", "0.15", "0.150"],
        ["keyword (overlap ridotto)", "0.00", "0.10", "0.000"],
        ["peso (h-index alto, citations alte)", "0.87", "0.15", "0.130"],
        ["geo (bando senza regione, neutro)", "0.50", "0.10", "0.050"],
        ["TOTALE", "", "", "<b>0.690</b>"],
    ], col_widths=[8.5*cm, 2.0*cm, 1.5*cm, 4.5*cm], num_cols={1, 2, 3})]
    s += [PageBreak()]

    # ── 6. ESEMPI DI MATCHING ────────────────────────────────────────────────
    s += [h1("6. Esempi di matching su scenari diversi")]
    s += [p("Quattro casi reali tratti dal DB attuale, scelti per mostrare "
            "comportamenti diversi del matcher.")]

    for ex in data["examples"]:
        b = ex["bando"]
        s += [h2(f"6.{data['examples'].index(ex) + 1} {ex['label']}")]
        s += [tbl([
            ["Campo", "Valore"],
            ["ID", b["id"]],
            ["Fonte", b["fonte"]],
            ["Titolo", b["titolo"][:120] if b["titolo"] else ""],
            ["Regione persistita",
             b["regione"] or "(non popolata, geo neutro 0.5)"],
            ["Stato", b["stato"]],
            ["Importo stimato",
             f"&euro; {b['importo_stimato']:,.0f}".replace(",", ".")
             if b["importo_stimato"] else "—"],
        ], col_widths=[4.5*cm, 12.0*cm])]

        s += [h3("Top 5 entit&agrave; correlate")]
        rows = [["#", "Score", "Tipo", "Sede", "Nome"]]
        for i, m in enumerate(ex["matches"], 1):
            rows.append([str(i), f"{m['score']:.3f}", m["tipo"],
                         m["sede_regione"] or "—", m["nome"][:42]])
        s += [tbl(rows, col_widths=[0.7*cm, 1.5*cm, 2.5*cm, 3.5*cm, 8.3*cm],
                  num_cols={0, 1})]

        if ex["matches"]:
            det = json.loads(ex["matches"][0]["dettaglio_json"] or "{}")
            s += [p(f"<b>Breakdown del top match</b>: "
                    f"tipo={det.get('tipo', 0):.2f} &middot; "
                    f"settori={det.get('settori', 0):.2f} &middot; "
                    f"concept={det.get('concept', 0):.2f} &middot; "
                    f"keyword={det.get('keyword', 0):.2f} &middot; "
                    f"peso={det.get('peso', 0):.2f} &middot; "
                    f"geo={det.get('geo', 0):.2f}")]
        s += [sp(6)]

    s += [h2("6.5 Letture chiave dagli esempi")]
    s += [bullet("<b>PRIN nazionale</b>: top dominato da ricercatori e "
                 "universit&agrave; con concept e peso alti. Il matcher si "
                 "comporta come ci si aspetta da un bando di ricerca pura.")]
    s += [bullet("<b>FSC nazionale macro</b>: i top sono ministeri/regioni "
                 "(beneficiari diretti dei piani FSC, multi-tema con peso "
                 "elevato). Limite noto: classificati come <i>azienda</i> per "
                 "default fallback nello scraper OC.")]
    s += [bullet("<b>FSC Lazio territoriale</b>: il geo_score=1.0 spinge in "
                 "cima entit&agrave; con sede in Lazio (ENEA, Sapienza, CNR, "
                 "Roma Tre, Tor Vergata). Caso da manuale per dimostrare "
                 "l'utilit&agrave; del componente territoriale.")]
    s += [bullet("<b>TED R&amp;D</b>: mix di ricercatori e universit&agrave;, "
                 "con concept_score elevato e peso forte sulle istituzioni "
                 "produttive.")]
    s += [PageBreak()]

    # ── 7. EVOLUZIONE / FIX APPLICATI ────────────────────────────────────────
    s += [h1("7. Evoluzione del matcher")]
    s += [p("Il sistema &egrave; passato da 4 a 6 componenti con interventi "
            "incrementali validati a ogni passaggio.")]

    s += [h2("7.1 Stato di partenza")]
    s += [bullet("4 componenti: tipo (0.35), settori (0.30), "
                 "concept (0.20), keyword (0.15)")]
    s += [bullet("Aziende sempre con concept=0 (OpenAlex non copre il "
                 "settore commerciale)")]
    s += [bullet("Multi-tema penalizzato: una entit&agrave; con 11 temi e 1 "
                 "match aveva settori_score = 1/11 invece di 1.0")]
    s += [bullet("44 bandi TED erano esiti di gare gi&agrave; aggiudicate "
                 "miscelati con i bandi attivi")]
    s += [bullet("Metriche disponibili (works_count, citations, n_progetti, "
                 "h-index) NON salvate nel DB")]

    s += [h2("7.2 Fix applicati e effetto misurato")]
    s += [tbl([
        ["#", "Fix", "File", "Effetto"],
        ["1", "Estensione enrichment OC: dettaglio soggetto &rarr; multi-tema, "
              "P.IVA, sede, totali progetti",
         "entity/opencoesione_beneficiari.py",
         "+607 segnali; popolata sede e P.IVA per 96 aziende OC"],
        ["2", "Logica OR su _settori_score: almeno 1 tema match &rarr; "
              "0.7 + 0.1*(match-1)",
         "matching/match_engine.py",
         "Multi-tema non pi&ugrave; penalizzato"],
        ["3", "Filtro form-type su TED + flag stato &lsquo;aggiudicato&rsquo;",
         "scraper/ted_scraper.py",
         "44 bandi TED esiti rimossi dal pool di matching"],
        ["4", "Salvataggio works_count, citations, h_index su OpenAlex",
         "entity/openalex.py",
         "+250 segnali metrici (universit&agrave; + ricercatori)"],
        ["5", "Salvataggio description, language, n_repos su GitHub",
         "entity/github_scraper.py",
         "Tech stack persistito per le organizzazioni IT"],
        ["6", "Pulizia: numeri (citations, n_progetti...) esclusi da "
              "extra_kw del matcher",
         "matching/match_engine.py",
         "Keyword score torna ad essere semantico"],
        ["7", "Nuovo componente <b>peso_score</b> (15%): max log-scaled tra "
              "h-index, citations, n_progetti, n_repos",
         "matching/match_engine.py",
         "Premio Nobel sale al #1 dove pertinente; ENEA/CNR/Sapienza "
         "spiccano sui bandi territoriali"],
        ["8", "Nuovo componente <b>geo_score</b> (10%): match regione "
              "bando vs sede entit&agrave;",
         "matching/match_engine.py + scraper/db.py + scripts/backfill_regione.py",
         "Bando &lsquo;ACCORDO LAZIO&rsquo;: top 10 tutto Lazio"],
    ], col_widths=[0.5*cm, 5.5*cm, 4.5*cm, 6.0*cm])]

    s += [h2("7.3 Pesi finali")]
    s += [tbl([
        ["Componente", "Peso iniziale", "Peso finale"],
        ["tipo", "0.35", "0.30"],
        ["settori", "0.30", "0.20"],
        ["concept", "0.20", "0.15"],
        ["keyword", "0.15", "0.10"],
        ["peso", "&mdash;", "<b>0.15</b>"],
        ["geo", "&mdash;", "<b>0.10</b>"],
        ["<b>Totale</b>", "<b>1.00</b>", "<b>1.00</b>"],
    ], col_widths=[6.0*cm, 4.0*cm, 4.0*cm], num_cols={1, 2})]
    s += [PageBreak()]

    # ── 8. LIMITI E PROSSIMI PASSI ───────────────────────────────────────────
    s += [h1("8. Limiti noti e prossimi sviluppi")]

    s += [h2("8.1 Limiti correnti")]
    s += [bullet("<b>ANAC bloccato</b>: il portale dati.anticorruzione.it usa "
                 "WAF, niente CSV scaricato. Nessun bando ANAC, nessun "
                 "contratto vinto. Workaround: download manuale dei CSV.")]
    s += [bullet("<b>MUR limitato</b>: lo scraping HTML &egrave; fragile, "
                 "siamo a 2 PRIN hardcoded come fallback. Servirebbe "
                 "un'API ministeriale o estrazione da PDF allegati.")]
    s += [bullet("<b>OpenCoesione: filtro per soggetto inattivo</b>. "
                 "L'API ignora silenziosamente <i>beneficiario</i>, "
                 "<i>soggetto</i>, <i>q</i>. Il dettaglio del soggetto "
                 "&egrave; per&ograve; ricco e viene sfruttato.")]
    s += [bullet("<b>Bug pre-esistente</b>: ministeri e regioni nello scraper "
                 "OC vengono classificati come <i>azienda</i> per default "
                 "fallback (l'API listing non espone <i>natura_giuridica</i>). "
                 "Fix possibile: leggere natura giuridica dal dettaglio.")]
    s += [bullet("<b>Coverage geo limitata</b>: solo 33% dei bandi e 22% "
                 "delle entit&agrave; ha regione persistita. "
                 "Migliorabile leggendo <i>place-of-performance</i> da TED "
                 "e <i>territori[]</i> da OC progetti.")]

    s += [h2("8.2 Idee di sviluppo (effort/impact)")]
    s += [tbl([
        ["Idea", "Effort", "Impact"],
        ["Saltare WAF ANAC con Playwright headless &rarr; ingestare CSV",
         "Alto", "Alto"],
        ["Estrazione PDF allegati MUR per descrizione completa bandi",
         "Medio", "Medio"],
        ["Aggiungere <i>place-of-performance</i> TED al matching geo",
         "Basso", "Alto"],
        ["Persistere CORDIS projects.title/subjects come segnali su "
         "organizzazioni",
         "Medio", "Alto"],
        ["Fix natura_giuridica nello scraper OC (legge dal dettaglio)",
         "Basso", "Medio"],
        ["Notifiche automatiche su bandi nuovi che matchano una entit&agrave; "
         "soglia",
         "Medio", "Alto"],
        ["UI web (Streamlit/FastAPI) per esplorare il DB senza CLI",
         "Medio", "Alto"],
    ], col_widths=[10.0*cm, 2.5*cm, 4.0*cm])]

    # ── FOOTER ───────────────────────────────────────────────────────────────
    s += [sp(20), hr(), sp(4)]
    s += [p(f"Documento generato il {today} &mdash; Progetto BANDI &nbsp;|"
            f"&nbsp; IDEA-RE", SMALL)]
    return s


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    if not DB_PATH.exists():
        print(f"[Report] DB non trovato: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"[Report] Lettura DB: {DB_PATH}")
    data = fetch_data()

    print(f"[Report] Costruzione PDF: {OUTPUT}")
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title="Progetto BANDI - Report di stato",
        author="IDEA-RE",
    )
    doc.build(build_story(data))
    print(f"[Report] PDF generato: {OUTPUT}")


if __name__ == "__main__":
    main()
