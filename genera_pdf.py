"""
Generatore PDF — Sistema BANDI
Tutte le celle delle tabelle usano Paragraph per garantire word-wrap corretto.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY, TA_RIGHT
import datetime

OUTPUT = r"C:\Users\andre\OneDrive\Desktop\BANDI\BANDI_Sistema_Analisi.pdf"

PAGE_W, PAGE_H = A4
L_MARGIN = 2.2 * cm
R_MARGIN = 2.2 * cm
BODY_W = PAGE_W - L_MARGIN - R_MARGIN   # larghezza utile testo

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=L_MARGIN,
    rightMargin=R_MARGIN,
    topMargin=2.5 * cm,
    bottomMargin=2.5 * cm,
    title="Sistema BANDI - Analisi Architetturale",
    author="IDEA-RE",
)

# ── Palette colori ────────────────────────────────────────────────────────────
NAVY    = colors.HexColor("#1a3a5c")
BLUE    = colors.HexColor("#2c5f8a")
LBLUE   = colors.HexColor("#e8f0f8")
LGREY   = colors.HexColor("#f5f5f5")
GRID_C  = colors.HexColor("#c0cfe0")
ALT_ROW = colors.HexColor("#f0f5fa")

# ── Stili testo ───────────────────────────────────────────────────────────────
def make_style(name, parent_name="Normal", **kw):
    base = getSampleStyleSheet()[parent_name]
    return ParagraphStyle(name, parent=base, **kw)

COVER_TITLE = make_style("CoverTitle",
    fontSize=28, fontName="Helvetica-Bold",
    textColor=NAVY, alignment=TA_CENTER,
    spaceBefore=0, spaceAfter=12, leading=34)

COVER_SUBT = make_style("CoverSubt",
    fontSize=13, fontName="Helvetica",
    textColor=BLUE, alignment=TA_CENTER,
    spaceBefore=0, spaceAfter=6, leading=18)

COVER_META = make_style("CoverMeta",
    fontSize=9, textColor=colors.grey,
    alignment=TA_CENTER, spaceBefore=0, spaceAfter=4)

H1 = make_style("H1",
    fontSize=17, fontName="Helvetica-Bold",
    textColor=NAVY,
    spaceBefore=22, spaceAfter=10, leading=22)

H2 = make_style("H2",
    fontSize=12, fontName="Helvetica-Bold",
    textColor=NAVY,
    spaceBefore=16, spaceAfter=8, leading=16,
    backColor=LBLUE,
    leftIndent=4, rightIndent=4,
    borderPad=5)

H3 = make_style("H3",
    fontSize=10, fontName="Helvetica-Bold",
    textColor=BLUE,
    spaceBefore=10, spaceAfter=6, leading=14)

BODY = make_style("Body",
    fontSize=9, leading=14,
    spaceBefore=0, spaceAfter=6,
    alignment=TA_JUSTIFY)

BULL = make_style("Bull",
    fontSize=9, leading=13,
    spaceBefore=0, spaceAfter=3,
    leftIndent=14, firstLineIndent=-8)

BULL_HDR = make_style("BullHdr",
    fontSize=9, leading=13,
    spaceBefore=3, spaceAfter=2,
    leftIndent=14, firstLineIndent=-8,
    fontName="Helvetica-Bold")

TOC = make_style("TOC",
    fontSize=9, leading=16,
    spaceBefore=2, spaceAfter=2,
    leftIndent=0)

TOC_SUB = make_style("TOCSub",
    fontSize=9, leading=15,
    spaceBefore=1, spaceAfter=1,
    leftIndent=16, textColor=colors.HexColor("#444444"))

CODE_S = make_style("Code",
    fontSize=8, fontName="Courier",
    leading=12,
    spaceBefore=4, spaceAfter=8,
    backColor=colors.HexColor("#f4f6f8"),
    leftIndent=8, rightIndent=8,
    borderPad=6,
    textColor=colors.HexColor("#1a1a2e"))

SMALL = make_style("Small",
    fontSize=8, textColor=colors.grey,
    spaceBefore=0, spaceAfter=3)

NOTE = make_style("Note",
    fontSize=8, textColor=colors.HexColor("#555555"),
    leftIndent=10, spaceBefore=4, spaceAfter=4,
    leading=12)

# ── Stili celle tabella ───────────────────────────────────────────────────────
CELL_HDR = make_style("CellHdr",
    fontSize=8, fontName="Helvetica-Bold",
    textColor=colors.white, leading=11,
    spaceBefore=0, spaceAfter=0)

CELL = make_style("Cell",
    fontSize=8, fontName="Helvetica",
    textColor=colors.black, leading=11,
    spaceBefore=0, spaceAfter=0)

CELL_MONO = make_style("CellMono",
    fontSize=7.5, fontName="Courier",
    textColor=colors.HexColor("#1a1a2e"), leading=11,
    spaceBefore=0, spaceAfter=0)

# ── Helpers ───────────────────────────────────────────────────────────────────
def sp(pts=8):
    return Spacer(1, pts)

def hr():
    return HRFlowable(width=BODY_W, thickness=0.5,
                      color=GRID_C, spaceBefore=4, spaceAfter=4)

def p(text, style=BODY):
    return Paragraph(text, style)

def h1(t):
    return Paragraph(t, H1)

def h2(t):
    return Paragraph(t, H2)

def h3(t):
    return Paragraph(t, H3)

def bullet(text, bold=False):
    s = BULL_HDR if bold else BULL
    return Paragraph(f"• {text}", s)

def note(text):
    return Paragraph(f"⚠️ {text}", NOTE)

def code_block(text):
    safe = (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
            .replace(" ", " "))
    return Paragraph(safe, CODE_S)


def _esc(text: str) -> str:
    """Escapes bare & in plain cell text so ReportLab XML parser doesn't choke."""
    import re
    # Escape & only when NOT already part of a named/numeric entity (&amp; &#...; &xxx;)
    return re.sub(r"&(?!(?:#\d+|#x[\da-fA-F]+|[a-zA-Z]\w*);)", "&amp;", str(text))


def _c(text, style=None, mono=False):
    """Crea un Paragraph per una cella di tabella."""
    if style is None:
        style = CELL_MONO if mono else CELL
    return Paragraph(_esc(str(text)), style)


def _ch(text):
    """Cella header (bianca su sfondo scuro)."""
    return Paragraph(_esc(str(text)), CELL_HDR)


def tbl(rows, col_widths, hdr_rows=1):
    """
    Crea una Table con word-wrap corretto.
    rows: lista di liste — le celle possono essere stringhe o Paragraph.
    Tutte le stringhe vengono wrappate automaticamente.
    """
    def wrap_row(row, is_header):
        return [
            _ch(cell) if is_header and not isinstance(cell, Paragraph)
            else (cell if isinstance(cell, Paragraph) else _c(cell))
            for cell in row
        ]

    wrapped = []
    for i, row in enumerate(rows):
        wrapped.append(wrap_row(row, i < hdr_rows))

    t = Table(wrapped, colWidths=col_widths, repeatRows=hdr_rows)
    t.setStyle(TableStyle([
        # Header
        ("BACKGROUND",    (0, 0), (-1, hdr_rows - 1), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, hdr_rows - 1), colors.white),
        # Righe alternate
        ("ROWBACKGROUNDS",(0, hdr_rows), (-1, -1), [colors.white, ALT_ROW]),
        # Font
        ("FONTNAME",      (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        # Griglia
        ("GRID",          (0, 0), (-1, -1), 0.3, GRID_C),
        ("LINEBELOW",     (0, 0), (-1, hdr_rows - 1), 1.0, NAVY),
        # Allineamento
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        # Padding uniforme
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# ═════════════════════════════════════════════════════════════════════════════
# CONTENUTO
# ═════════════════════════════════════════════════════════════════════════════
story = []

# ── COPERTINA ─────────────────────────────────────────────────────────────────
story += [
    sp(80),
    Paragraph("SISTEMA BANDI", COVER_TITLE),
    sp(6),
    Paragraph(
        "Architettura per raccolta, archiviazione e matching<br/>di bandi pubblici italiani ed europei",
        COVER_SUBT),
    sp(16),
    hr(),
    sp(8),
    Paragraph(f"Documento di analisi &mdash; {datetime.date.today().strftime('%d %B %Y')}", COVER_META),
    Paragraph("Realizzato da: IDEA-RE &nbsp;|&nbsp; atenerini@idea-re.eu", COVER_META),
    PageBreak(),
]

# ── INDICE ────────────────────────────────────────────────────────────────────
story += [
    h1("Indice"),
    sp(4),
]
toc_entries = [
    ("1.", "Obiettivo del sistema", False),
    ("2.", "Architettura generale", False),
    ("3.", "BANDI &mdash; Fonti e API", False),
    ("3.1", "Fonti nazionali italiane", True),
    ("3.2", "Fonti europee", True),
    ("3.3", "Enti di ricerca internazionali", True),
    ("3.4", "Regioni italiane", True),
    ("3.5", "Tipologie di bandi (tassonomia)", True),
    ("3.6", "Note tecniche API TED", True),
    ("3.7", "Esempi reali scaricati", True),
    ("4.", "AZIENDE / ENTI / RICERCATORI &mdash; Profili", False),
    ("4.1", "Schema del profilo entit&agrave;", True),
    ("4.2", "Livelli di affidabilit&agrave; segnali", True),
    ("4.3", "Fonti gratuite", True),
    ("4.4", "Fonti italiane specifiche", True),
    ("4.5", "Fonti social e comportamentali", True),
    ("5.", "Fonti a pagamento &mdash; Costi e registrazione", False),
    ("6.", "Piano di implementazione", False),
]
for num, title, sub in toc_entries:
    s = TOC_SUB if sub else TOC
    story.append(Paragraph(f"<b>{num}</b>&nbsp;&nbsp;{title}", s))
story += [PageBreak()]


# ── 1. OBIETTIVO ──────────────────────────────────────────────────────────────
story += [
    h1("1. Obiettivo del sistema"),
    sp(4),
    p("Il sistema automatizza la raccolta di bandi pubblici da fonti eterogenee "
      "(italiane, europee, enti di ricerca), li archivia in un database normalizzato, "
      "costruisce profili strutturati di aziende, ricercatori ed enti, ed esegue un "
      "matching intelligente per proporre proattivamente le opportunit&agrave; giuste "
      "alle entit&agrave; giuste."),
    sp(6),
    p("Il valore differenziale non &egrave; nella semplice aggregazione di bandi "
      "(esistono gi&agrave; aggregatori), ma nel <b>matching di qualit&agrave;</b>: "
      "non solo per settore formale (ATECO/CPV), ma per interesse reale dimostrato "
      "da evidenze comportamentali &mdash; contratti vinti, brevetti, job posting, "
      "pubblicazioni del management, partecipazione a progetti EU."),
]

# ── 2. ARCHITETTURA ───────────────────────────────────────────────────────────
story += [
    sp(6),
    h1("2. Architettura generale"),
    sp(4),
    code_block(
        "[Scraper Bandi]               [Scraper Entita]\n"
        "  TED API v3                    OpenAlex / ORCID\n"
        "  ANAC bulk CSV                 CORDIS / EPO\n"
        "  MUR / MIMIT scraper           ANAC aggiudicatari\n"
        "       |                               |\n"
        "       v                               v\n"
        " [Normalizzazione]          [Arricchimento profili]\n"
        "       |                               |\n"
        "       +-----------> [SQLite DB] <-----+\n"
        "                           |\n"
        "                 [Motore di Matching]\n"
        "               (embedding vettoriale + CPV)\n"
        "                           |\n"
        "              [Output: email / dashboard / API]"
    ),
    sp(6),
    p("<b>Approccio matching:</b> embeddings semantici sulla combinazione di CPV "
      "bando + descrizione + tassonomia EuroSciVoc vs vettore profilo entit&agrave; "
      "(CPV storici ANAC + keywords job posting + concetti OpenAlex + CPC brevetti). "
      "Cosine similarity &rarr; score di affinit&agrave; per ogni coppia bando/entit&agrave;."),
]


# ── 3. BANDI ─────────────────────────────────────────────────────────────────
story += [PageBreak(), h1("3. BANDI &mdash; Fonti e API")]

# 3.1
W = BODY_W
story += [
    sp(4),
    KeepTogether([
        h2("3.1 Fonti nazionali italiane"),
        sp(4),
        tbl(
            [
                ["Ente", "Tipo bandi", "Portale", "API / Accesso"],
                ["ANAC",
                 "Appalti pubblici (forniture, servizi, lavori)",
                 "dati.anticorruzione.it",
                 "REST+OCDS bloccato da WAF → bulk CSV ZIP"],
                ["MIT / SCP",
                 "Contratti pubblici infrastrutture",
                 "dati.mit.gov.it",
                 "Open Data OCDS, agg. giornaliero"],
                ["MUR",
                 "PRIN, PNRA, dottorati innovativi",
                 "prin.mur.gov.it",
                 "No API → scraper HTML"],
                ["MIMIT",
                 "Incentivi imprese, patent box",
                 "mimit.gov.it/incentivi",
                 "No API → scraper HTML"],
                ["Invitalia",
                 "Smart&Start, Resto al Sud, Cultura",
                 "invitalia.it",
                 "No API → sito JS-heavy (Playwright)"],
                ["OpenCoesione",
                 "FESR, FSE+, PNRR, fondi strutturali",
                 "opencoesione.gov.it",
                 "Open Data CSV/JSON"],
            ],
            [2.8*cm, 4.2*cm, 4.0*cm, 5.2*cm]
        ),
        sp(6),
    ]),
]

# 3.2
story += [
    KeepTogether([
        h2("3.2 Fonti europee"),
        sp(4),
        tbl(
            [
                ["Ente", "Tipo bandi", "Portale", "API"],
                ["TED — Tenders Electronic Daily",
                 "Appalti pubblici EU sopra soglia comunitaria",
                 "ted.europa.eu",
                 "REST API v3 — funzionante, no auth"],
                ["EU Funding & Tenders Portal",
                 "Horizon Europe, ERC, MSCA, Digital Europe, Erasmus+",
                 "ec.europa.eu/funding",
                 "No API diretta — ricerca web"],
                ["ERC",
                 "Starting, Consolidator, Advanced, Synergy Grant",
                 "erc.europa.eu",
                 "Parte del portale EU F&T"],
                ["CORDIS / OpenAIRE",
                 "Tutti i progetti EU finanziati (H2020+HEU)",
                 "cordis.europa.eu",
                 "OpenAIRE Graph API v1 (gratuita)"],
            ],
            [3.2*cm, 4.0*cm, 3.8*cm, 5.2*cm]
        ),
        sp(6),
    ]),
]

# 3.3
story += [
    KeepTogether([
        h2("3.3 Enti di ricerca internazionali"),
        sp(4),
        tbl(
            [
                ["Ente", "Portale", "API / Accesso"],
                ["CERN", "procurement.cern.ch",
                 "No API — web scraping HTML"],
                ["ESA", "esa-star (ex EMITS)",
                 "No API — portale web registrazione"],
                ["INFN", "jobs.dsi.infn.it + ac.infn.it",
                 "No API — web scraping"],
                ["EIB / EIF", "eib.org/en/projects",
                 "Open Data parziale"],
            ],
            [2.8*cm, 5.5*cm, 7.9*cm]
        ),
        sp(6),
    ]),
]

# 3.4
story += [
    KeepTogether([
        h2("3.4 Regioni italiane"),
        sp(4),
        tbl(
            [
                ["Regione", "Portale bandi", "API / Open Data"],
                ["Lombardia", "bandi.regione.lombardia.it",
                 "dati.lombardia.it — API Socrata"],
                ["Piemonte", "bandi.regione.piemonte.it",
                 "Open data parziale"],
                ["Veneto", "regione.veneto.it/bandi",
                 "Web scraping"],
                ["Toscana, Emilia, altre", "Portali regionali separati",
                 "Principalmente web scraping"],
            ],
            [2.8*cm, 5.5*cm, 7.9*cm]
        ),
        sp(6),
    ]),
]

# 3.5
story += [
    KeepTogether([
        h2("3.5 Tipologie di bandi — Tassonomia"),
        sp(4),
        tbl(
            [
                ["Categoria", "Sottotipologie", "Fonti principali"],
                ["Appalti Pubblici",
                 "Forniture · Servizi · Lavori",
                 "TED, ANAC, MIT/SCP"],
                ["Ricerca & Sviluppo",
                 "PRIN · Horizon (ERC/EIC/MSCA) · Bilaterali · Borse",
                 "MUR, EU F&T Portal, ERC"],
                ["Incentivi Imprese",
                 "Startup · PMI digitale · Internazionalizzazione · Sud",
                 "Invitalia, MIMIT, CDP"],
                ["Fondi Strutturali UE",
                 "FESR · FSE+ · PNRR · POR regionali",
                 "OpenCoesione, Regioni"],
                ["Formazione & Lavoro",
                 "Voucher · Tirocini EU · Concorsi PA",
                 "ESA, CERN, portali PA"],
            ],
            [3.8*cm, 5.5*cm, 6.9*cm]
        ),
        sp(6),
    ]),
]

# 3.6
story += [
    h2("3.6 Note tecniche — API TED (unica API REST testata e funzionante)"),
    sp(4),
    p("<b>Endpoint:</b> POST https://api.ted.europa.eu/v3/notices/search"),
    p("<b>Autenticazione:</b> nessuna &mdash; accesso pubblico"),
    sp(4),
    p("<b>Esempio body corretto:</b>"),
    code_block(
        '{\n'
        '  "query": "buyer-country=ITA AND dispatch-date>=20260101\n'
        '           AND classification-cpv=73000000",\n'
        '  "fields": ["ND","TI","organisation-name-buyer",\n'
        '             "estimated-value-lot","deadline-date-lot",\n'
        '             "classification-cpv","description-lot",\n'
        '             "dispatch-date","links"],\n'
        '  "limit": 50,\n'
        '  "scope": "ALL",\n'
        '  "checkQuerySyntax": false,\n'
        '  "paginationMode": "ITERATION"\n'
        '}'
    ),
    sp(4),
    p("<b>Errori comuni da evitare:</b>"),
    bullet("cpv-code (errato) → usare classification-cpv"),
    bullet("PC=IT (errato) → usare buyer-country=ITA"),
    bullet("NC=2 (errato) → il campo NC usa codifica eForms diversa dai codici classici"),
    bullet("scope=ACTIVE → inaffidabile per record storici; usare scope=ALL + filtro data"),
    bullet("GET request → TED richiede POST; usare Python requests o PowerShell Invoke-RestMethod"),
    sp(6),
]

# 3.7
story += [
    KeepTogether([
        h2("3.7 Esempi reali scaricati (Desktop/BANDI/esempi/)"),
        sp(4),
        tbl(
            [
                ["File JSON", "Categoria", "Ente / Oggetto", "Importo", "Scadenza"],
                ["TED_7451-2026",
                 "Appalto Servizi",
                 "EFSA — Metodi statistici ecotossicologia",
                 "€ 720.000", "05/01/2026"],
                ["TED_13257-2026",
                 "Appalto Servizi",
                 "JRC — Guidelines development (oncologia)",
                 "€ 400.000", "07/01/2026"],
                ["PRIN_2026",
                 "Ricerca Nazionale",
                 "MUR — PRIN 2026 (dotaz. €260M)",
                 "€1M–€1,2M / progetto", "01/06/2026"],
                ["SmartStart_2026",
                 "Incentivo Imprese",
                 "Invitalia — Smart&Start Italia",
                 "€100K–€1,5M", "Sportello aperto"],
            ],
            [2.8*cm, 2.8*cm, 5.5*cm, 2.8*cm, 2.3*cm]
        ),
        sp(4),
        p("Ogni file contiene i dati grezzi della fonte e un campo "
          "<b>schema_normalizzato</b> con struttura comune: id, titolo, ente, "
          "paese, importo, scadenza, tipo, settori, destinatari."),
        sp(6),
    ]),
    PageBreak(),
]


# ── 4. ENTITÀ ─────────────────────────────────────────────────────────────────
story += [h1("4. AZIENDE / ENTI / RICERCATORI — Profili")]

# 4.1
story += [
    sp(4),
    h2("4.1 Schema del profilo entità"),
    sp(4),
    code_block(
        '{\n'
        '  "id": "azienda-XYZ",\n'
        '  "tipo": "azienda | universita | ente_ricerca | ricercatore",\n'
        '  "identita_formale": {\n'
        '      "ragione_sociale", "piva", "ateco_2025",\n'
        '      "dimensione", "sede", "amministratori"\n'
        '  },\n'
        '  "storico_contratti": {\n'
        '      "appalti_vinti_anac": 12,\n'
        '      "cpv_prevalenti": ["73000000","72000000"],\n'
        '      "valore_totale_eur": 4200000\n'
        '  },\n'
        '  "partecipazione_ricerca": {\n'
        '      "progetti_cordis": [...],\n'
        '      "topic_euroscivoc": [...],\n'
        '      "prin_vinti": [...]\n'
        '  },\n'
        '  "segnali_interesse": {\n'
        '      "job_postings_keywords": ["machine learning","clinical trials"],\n'
        '      "brevetti_cpc": ["G16H","A61B"],\n'
        '      "news_topics": ["AI diagnostica"],\n'
        '      "sito_web_keywords": ["salute digitale","telemedicina"]\n'
        '  },\n'
        '  "profilo_management": {\n'
        '      "ceo_orcid": "0000-0001-XXXX-XXXX",\n'
        '      "ceo_pubblicazioni": 8,\n'
        '      "ceo_settori_ricerca": ["informatica medica"]\n'
        '  }\n'
        '}'
    ),
    sp(6),
]

# 4.2
story += [
    KeepTogether([
        h2("4.2 Livelli di affidabilità dei segnali"),
        sp(4),
        tbl(
            [
                ["Livello", "Tipo segnale", "Fonti", "Qualità"],
                ["5 — Hanno già fatto",
                 "Contratti vinti, grant ricevuti, brevetti depositati",
                 "ANAC, CORDIS, EPO, MUR",
                 "Massima"],
                ["4 — Intenzione dichiarata",
                 "Job posting, conferenze, cluster membership",
                 "TheirStack, Sessionize, cluster MUR",
                 "Alta"],
                ["3 — Affinità inferita",
                 "Sito web, GitHub repos, YouTube, news",
                 "Scraping, GitHub API, GDELT",
                 "Media"],
                ["2 — Segnale debole",
                 "Fiere, eventi, social following",
                 "Fiera Milano, Eventbrite, LinkedIn",
                 "Bassa"],
                ["1 — Settore formale",
                 "Codice ATECO / CPV dichiarato",
                 "Registro Imprese, Telemaco",
                 "Minima"],
            ],
            [3.0*cm, 5.0*cm, 4.5*cm, 3.7*cm]
        ),
        sp(6),
    ]),
]

# 4.3
story += [
    h2("4.3 Fonti gratuite — dettaglio"),
    sp(4),
    tbl(
        [
            ["Fonte", "Dati chiave", "API", "Priorità"],
            ["ANAC open data",
             "Appalti vinti: CPV, importo, ente, anno",
             "Bulk CSV (WAF blocca REST)",
             "P1"],
            ["CORDIS / OpenAIRE",
             "Progetti H2020/HEU: topic EuroSciVoc, ruolo, funding",
             "OpenAIRE Graph API v1",
             "P1"],
            ["OpenAlex",
             "209M paper, 13M autori, concetti, affiliazioni IT",
             "REST gratuita",
             "P1"],
            ["ORCID",
             "Keywords ricercatori, employment, grants dichiarati",
             "REST gratuita",
             "P1"],
            ["EPO Open Patent Services",
             "Brevetti per titolare IT, classificazione CPC",
             "REST gratuita (4 GB/sett.)",
             "P1"],
            ["TED aggiudicazioni",
             "Contratti EU vinti (campo award), importo, ente",
             "TED API v3 (testata)",
             "P1"],
            ["Semantic Scholar",
             "200M+ paper, embeddings, recommendations",
             "REST gratuita",
             "P2"],
            ["arXiv API",
             "Preprint: fisica, CS, matematica, bio",
             "REST gratuita",
             "P2"],
            ["GDELT",
             "News mentions aziende + topic, aggiorn. 15 min",
             "BigQuery gratuito",
             "P2"],
            ["GitHub API",
             "Repos aziendali, topics, linguaggi, stars",
             "REST (5.000 req/ora con token)",
             "P2"],
            ["OpenCoesione",
             "Fondi strutturali ricevuti per beneficiario",
             "CSV open data",
             "P2"],
            ["Wikidata SPARQL",
             "Struttura org, settori, fondatori (grandi enti)",
             "SPARQL gratuita",
             "P3"],
        ],
        [3.2*cm, 5.2*cm, 4.0*cm, 1.8*cm]
    ),
    sp(6),
]

# 4.4
story += [
    KeepTogether([
        h2("4.4 Fonti italiane specifiche (gratuite/scrapabili)"),
        sp(4),
        tbl(
            [
                ["Fonte", "Segnale", "Come accedere"],
                ["Cluster Tecnologici Nazionali MUR",
                 "Membership = settore dichiarato (12 cluster)",
                 "Web scraping siti cluster"],
                ["Parchi Scientifici e Tecnologici",
                 "Tenant = tipo di ricerca e settore",
                 "Web scraping portali PST"],
                ["IRIS / AMS (repos universitari)",
                 "Produzione scientifica per dipartimento",
                 "Protocollo OAI-PMH"],
                ["Fiere (Fiera Milano, BolognaFiere)",
                 "Elenchi espositori per categoria merceologica",
                 "Web scraping cataloghi"],
                ["Sessionize / Papercall",
                 "Speaker = topic presentato pubblicamente",
                 "Web scraping"],
                ["Gazzetta Ufficiale",
                 "Menzioni in decreti, autorizzazioni settoriali",
                 "API Normattiva / scraping"],
            ],
            [3.8*cm, 5.5*cm, 6.9*cm]
        ),
        sp(6),
    ]),
]

# 4.5
story += [
    KeepTogether([
        h2("4.5 Fonti social e comportamentali"),
        sp(4),
        tbl(
            [
                ["Fonte", "Segnale", "Costo", "Note"],
                ["Job posting (portali aziendali)",
                 "Cosa assumono = dove investono",
                 "Gratis (scraping)",
                 "Segnale più predittivo"],
                ["GitHub Organizations",
                 "Repos, topics, tecnologie R&D",
                 "Gratis API",
                 "Ottimo per tech company"],
                ["YouTube (canale aziendale)",
                 "Argomenti video, tag, descrizioni",
                 "Gratis API v3",
                 "Segnale medio"],
                ["Medium / Substack (CTO/CEO)",
                 "Articoli su certi topic",
                 "Scraping",
                 "Segnale forte se presente"],
                ["Crunchbase (free tier)",
                 "Categoria startup, investitori, funding",
                 "Limitato senza piano",
                 "Utile per startup"],
                ["F6S",
                 "Applicazioni a programmi innovazione EU",
                 "Parzialmente free",
                 "Startup e PMI innovative"],
            ],
            [3.2*cm, 4.5*cm, 2.8*cm, 5.7*cm]
        ),
        sp(6),
    ]),
    PageBreak(),
]


# ── 5. FONTI A PAGAMENTO ─────────────────────────────────────────────────────
story += [h1("5. Fonti a pagamento — Costi e registrazione")]

# 5.1
story += [
    sp(4),
    KeepTogether([
        h2("5.1 Telemaco / InfoCamere (Registro Imprese ufficiale)"),
        sp(4),
        p("<b>Modello:</b> pay-per-use su credito prepagato — nessun canone fisso.<br/>"
          "<b>Registrazione:</b> gratuita su registroimprese.it"),
        sp(4),
        tbl(
            [
                ["Documento", "Costo"],
                ["Ricerca anagrafica", "€ 0,60"],
                ["Scheda persona (cariche / ruoli)", "€ 0,70"],
                ["Soci e partecipazioni (blocco complesso)", "€ 2,00"],
                ["Visura ordinaria SPA/SRL", "€ 5,00"],
                ["Visura storica SPA/SRL", "€ 6,00"],
                ["Bilancio depositato (copia)", "€ 2,50"],
                ["Prospetto Contabile XBRL", "€ 0,80"],
                ["Fascicolo completo società di capitali", "€ 10,00"],
                ["Elenco imprese (per posizione)", "€ 0,02 / riga"],
            ],
            [12.5*cm, 3.7*cm]
        ),
        sp(6),
    ]),
]

# 5.2
story += [
    KeepTogether([
        h2("5.2 OpenAPI.com — Dati aziendali arricchiti"),
        sp(4),
        p("<b>Modello:</b> pay-per-call con sconti volume.<br/>"
          "<b>Free tier:</b> 30 call/mese su IT-start e IT-advanced.<br/>"
          "<b>Registrazione:</b> console.openapi.com/register"),
        sp(4),
        tbl(
            [
                ["Endpoint", "Dati inclusi", "Prezzo singolo", "Prezzo volume"],
                ["IT-start",
                 "Dati base + ATECO + sede",
                 "€ 0,050", "€ 0,015 (−70%)"],
                ["IT-advanced",
                 "+ fatturato + dipendenti + email + PEC",
                 "€ 0,100", "€ 0,028 (−72%)"],
                ["IT-full",
                 "+ soci + cariche + bilanci + social",
                 "€ 0,300", "€ 0,089 (−70%)"],
                ["IT-ubo",
                 "Titolare effettivo (UBO)",
                 "€ 1,100", "€ 0,880 (−20%)"],
            ],
            [2.2*cm, 6.3*cm, 2.8*cm, 4.9*cm]
        ),
        sp(6),
    ]),
]

# 5.3
story += [
    KeepTogether([
        h2("5.3 Atoka / SpazioDati (Cerved Group)"),
        sp(4),
        p("<b>Modello:</b> enterprise su preventivo. Il piano Atoka Start "
          "è stato dismesso dal 10/12/2025.<br/>"
          "<b>Contatto:</b> atoka.io/it/contact-us — token di prova gratuito disponibile."),
        sp(4),
        tbl(
            [
                ["Prodotto", "Contenuto", "Stima prezzo"],
                ["Atoka Evolution API",
                 "6M aziende IT, 13M manager, 70K+ news/giorno, social, tecnologie",
                 "€ 500–2.000/mese (da negoziare)"],
                ["Atoka PA",
                 "Storico appalti pubblici vinti + gare attive",
                 "Su preventivo separato"],
            ],
            [3.2*cm, 8.0*cm, 5.0*cm]
        ),
        sp(6),
    ]),
]

# 5.4
story += [
    KeepTogether([
        h2("5.4 RocketReach — Profili manager e contatti"),
        sp(4),
        p("<b>Registrazione:</b> rocketreach.co (self-service con carta, "
          "piano annuale consigliato per risparmio)"),
        sp(4),
        tbl(
            [
                ["Piano", "Crediti/anno", "API", "Costo annuale"],
                ["Essentials", "1.200 lookup", "No", "~ € 370/anno"],
                ["Pro", "6.000 export", "Limitata", "~ € 830/anno"],
                ["Ultimate", "Illimitato", "Completa", "~ € 1.950/anno"],
                ["Enterprise", "Custom", "Custom", "da $ 6.000/anno"],
            ],
            [3.0*cm, 3.5*cm, 3.0*cm, 6.7*cm]
        ),
        sp(4),
        p("Eccedenze: $0,30–$0,45 per lookup aggiuntivo."),
        sp(6),
    ]),
]

# 5.5
story += [
    KeepTogether([
        h2("5.5 Crunchbase — Startup, funding, investitori"),
        sp(4),
        p("<b>Registrazione:</b> crunchbase.com (self-service con carta)"),
        sp(4),
        tbl(
            [
                ["Piano", "Costo mensile", "Costo annuale", "API"],
                ["Pro", "$99/mese", "$588/anno ($49/mese)", "No"],
                ["Business", "$199/mese", "$2.388/anno", "No"],
                ["Enterprise", "—", "da $50.000/anno", "Sì"],
            ],
            [3.0*cm, 3.5*cm, 4.5*cm, 5.2*cm]
        ),
        sp(6),
    ]),
]

# 5.6
story += [
    KeepTogether([
        h2("5.6 TheirStack — Job posting + technographics"),
        sp(4),
        p("<b>Registrazione:</b> app.theirstack.com/signup "
          "(email, attivazione immediata)"),
        sp(4),
        tbl(
            [
                ["Piano", "Company credits/mese", "API credits/mese", "Costo"],
                ["Free", "50", "200", "€ 0"],
                ["Starter", "—", "—", "~ $59/mese"],
                ["Pro", "—", "—", "~ $169/mese"],
            ],
            [3.0*cm, 4.2*cm, 4.2*cm, 4.8*cm]
        ),
        sp(4),
        p("Costo per record: $0,0015–$0,039 per job posting. "
          "Rollover crediti fino a 12 mesi."),
        sp(6),
    ]),
]

# 5.7
story += [
    KeepTogether([
        h2("5.7 Scopus (Elsevier) e EPO Open Patent Services"),
        sp(4),
        tbl(
            [
                ["Fonte", "Modello", "Costo", "Registrazione"],
                ["Scopus / Elsevier",
                 "Istituzionale (univ. con abbonamento): gratuito. "
                 "Commerciale: su contratto.",
                 "Commerciale: decine k€/anno",
                 "dev.elsevier.com (richiede abbonamento istituzionale)"],
                ["EPO Open Patent Services",
                 "Gratuito per uso non commerciale (4 GB/settimana)",
                 "€ 0 (free tier)",
                 "developers.epo.org/user/register"],
            ],
            [2.5*cm, 5.5*cm, 3.3*cm, 4.9*cm]
        ),
        sp(6),
    ]),
    PageBreak(),
]


# ── 6. PIANO DI IMPLEMENTAZIONE ───────────────────────────────────────────────
story += [
    h1("6. Piano di implementazione"),
    sp(4),
    KeepTogether([
        h2("Fase 1 — Prototipo (costo: € 0)"),
        sp(4),
        p("Utilizzo esclusivo di fonti gratuite per il primo prototipo funzionante:"),
        sp(4),
        tbl(
            [
                ["Componente", "Fonti", "Output"],
                ["Scraper bandi",
                 "TED API v3, ANAC bulk CSV, OpenAIRE, MUR HTML",
                 "DB bandi normalizzato"],
                ["Scraper entità",
                 "OpenAlex, ORCID, EPO OPS, GDELT, GitHub API, TheirStack free",
                 "DB profili entità con segnali"],
                ["Matching engine",
                 "Embeddings su descrizione bando vs profilo entità",
                 "Score affinità per coppia"],
                ["Output",
                 "JSON / CSV match ranked",
                 "Pronto per validazione manuale"],
            ],
            [3.2*cm, 6.0*cm, 7.0*cm]
        ),
        sp(6),
    ]),
    KeepTogether([
        h2("Fase 2 — MVP con dati reali (costo: ~ € 150–300/mese)"),
        sp(4),
        tbl(
            [
                ["Fonte aggiunta", "Costo stimato", "Valore aggiunto"],
                ["OpenAPI.com IT-advanced",
                 "~ €0,028 × N aziende",
                 "ATECO preciso + email + fatturato + dipendenti"],
                ["TheirStack Starter",
                 "$59/mese",
                 "Job posting estesi — segnale di investimento reale"],
                ["Telemaco ricarica",
                 "€ 50–100 una tantum",
                 "Soci + cariche + bilanci ufficiali"],
                ["Crunchbase Pro",
                 "$49/mese (annuale)",
                 "Startup italiane per settore/funding"],
            ],
            [3.8*cm, 3.5*cm, 8.9*cm]
        ),
        sp(6),
    ]),
    KeepTogether([
        h2("Fase 3 — Prodotto scalato (costo: ~ € 800–2.500/mese)"),
        sp(4),
        tbl(
            [
                ["Fonte aggiunta", "Costo stimato", "Valore aggiunto"],
                ["Atoka Evolution API",
                 "€ 500–2.000/mese",
                 "Manager linkati ad aziende + news real-time + social"],
                ["RocketReach Ultimate",
                 "~ € 160/mese",
                 "Email/profilo manager per outreach diretto"],
                ["TheirStack Pro",
                 "$169/mese",
                 "Copertura completa job posting italiani ed europei"],
                ["Scopus",
                 "Istituzionale gratis / enterprise su contratto",
                 "H-index e impact factor ricercatori certificati"],
            ],
            [3.8*cm, 3.5*cm, 8.9*cm]
        ),
        sp(12),
    ]),
    hr(),
    sp(4),
    p("Documento generato il " +
      datetime.date.today().strftime("%d/%m/%Y") +
      " &mdash; Progetto BANDI &nbsp;|&nbsp; IDEA-RE",
      SMALL),
]


# ── BUILD ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    doc.build(story)
    print(f"PDF generato: {OUTPUT}")
