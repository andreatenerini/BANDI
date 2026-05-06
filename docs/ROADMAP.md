# BANDI — Roadmap architetturale

> Documento di design delle 5 fasi per portare il progetto da "snapshot di test"
> a "DB locale completo + matching ottimizzato + pipeline background".
>
> Generato: 2026-05-06. Stato di partenza: 333 bandi (~52 attivi reali) e 307 entità.

---

## Visione

Costruire e mantenere aggiornati **due cataloghi locali** integrati da un motore di matching:

1. **Catalogo Bandi** — opportunità di finanziamento attive accessibili a soggetti italiani
   (UE, Stato, Regioni, ricerca, PA).
2. **Catalogo Fruitori** — entità potenziali destinatarie (aziende, ricercatori,
   università, enti, no-profit) con il massimo dettaglio utile al matching.

Il matching deve essere ricalcolabile in pochi secondi e produrre top-N entità
per ogni bando attivo, con breakdown spiegabile dei componenti (oggi 6, vedi
`matching/match_engine.py`).

---

## Stato di partenza (snapshot 2026-05-06)

| Metrica | Valore |
|---|---:|
| Bandi totali | 333 |
| Bandi *davvero attivi a cui candidarsi* | ~52 (TED competition + 2 PRIN MUR) |
| Entità totali | 307 |
| Entità con sede regione | 68 (22%) |
| Entità con P.IVA | ~96 (solo OC arricchite) |
| Entità con ATECO | 0 (campo mai popolato) |
| Segnali totali | 2.392 |
| Match calcolati | 5.320 |

**Bandi importati per fonte**:
- TED: 50 attivi + 18 scaduti + 44 aggiudicati (filtrati out)
- OpenCoesione: 214 attivi (ma sono **progetti già finanziati**, non bandi aperti) + 5 scaduti
- MUR: 2 (PRIN hardcoded)
- ANAC: **0** (WAF block)

**Cosa manca strutturalmente**: bandi MUR oltre i PRIN, bandi ANAC, bandi regionali,
bandi UE non-TED (Horizon, Erasmus+, EIC), arricchimento ATECO/dimensione delle
aziende, descrizioni testuali siti aziendali, pubblicazioni recenti dei ricercatori.

---

## Fase 1 — Massimizzare le fonti già implementate

**Obiettivo**: raggiungere il limite naturale di TED, OC e MUR senza nuovo codice
di scraping. Solo aumentare i parametri.

### Modifiche puntuali

| File | Parametro | Da | A |
|---|---|---:|---:|
| `scraper/ted_scraper.py` `__main__` | `days_back` | 60 | 365 |
| stesso | `max_pages` | 5 | 100 |
| `scraper/ted_scraper.py` `PRESET_QUERIES` | n. query | 5 | aggiungere `it_costruzioni`, `it_sanita`, `it_ambiente`, `it_consulenza` |
| `scraper/opencoesione_scraper.py` `__main__` | `max_per_tema` | 50 | 2000 |
| `entity/opencoesione_beneficiari.py` `__main__` | `max_per_tema` | 100 | 1000 |

### Risultato atteso

- TED: da 112 → **~5.000-15.000 bandi** (90% storici/scaduti, ~500-1.500 attivi)
- OC: da 219 → **~10.000-15.000 progetti** (storici, utili come profilazione)
- Aziende OC: da ~191 → **~5.000-8.000** con dati arricchiti

### Costo

- Tempo di scrape: ~1-3 ore per run
- Banda: trascurabile (~50-100 MB)
- Storage DB: da 4 MB a ~100-200 MB (nota: dovrà uscire dal repo, già in `.gitignore`)
- Rate limit: rispettati con sleep esistenti (0.4s OC, 0.5s TED)

### Effort di implementazione

**Basso (30-60 minuti)**: solo modifica numeri. Ma il run è lungo (background).

---

## Fase 2 — Sbloccare ANAC con Playwright

**Obiettivo**: aggirare il WAF e scaricare i CSV bulk OCDS di ANAC, popolando
`bandi` (gare attive) e soprattutto `contratti_vinti` (oggi a 0 — segnale forte
per le aziende).

### Approccio tecnico

Playwright avvia un browser Chromium reale (headless o con UI), navigando il
portale come farebbe un umano. Il WAF distingue browser veri da `requests` via
TLS fingerprint, ordine header HTTP/2, presenza di JS execution, cookie
challenge. Playwright supera tutto questo.

### Codice da scrivere

```
scraper/anac_playwright.py    # nuovo file
  - apre browser headless chromium
  - naviga a https://dati.anticorruzione.it/opendata
  - cerca dataset "appalti_ocds_<anno>"
  - clicca download del CSV
  - aspetta che il file sia completo
  - sposta in data/raw/anac/
```

### Dipendenze

```
pip install playwright
playwright install chromium       # ~150 MB di download
```

### Volume dati

ANAC pubblica circa **1 milione di procedure/anno**. Il CSV `appalti_ocds_2026.csv`
è ~500 MB compresso. Importarlo tutto satura il DB. Strategia:
- Limitare a ultimi N giorni di pubblicazione (`--days-back 90`)
- Filtrare per `tender.status='active'` e `tenderPeriod.endDate > today`
- Frammentare l'import in chunk con commit ogni 10.000 righe

### Risultato atteso

- Bandi ANAC attivi: **~30.000-50.000**
- Aggiudicatari (per `entity/anac_winners.py`): **~500.000+** (dati storici 2-3 anni)
- Segnali `cpv_vinto` su aziende esistenti: ~10x boost al match per le aziende
  che hanno storia di contratti pubblici

### Effort di implementazione

**Medio (3-5 ore)**: installazione Playwright, scrittura scraper, gestione
download, import CSV, test su anno corrente.

### Rischi

- Playwright potrebbe essere a sua volta detettato (improbabile, ANAC non è
  particolarmente sofisticato)
- Cambio della struttura HTML del portale rompe lo scraper (fragile, ma
  ricuperabile)
- Volume dati: 500 MB CSV importato tutto rallenta i match. Va filtrato.

---

## Fase 3 — Nuove fonti bandi italiani

**Obiettivo**: coprire le aree non raggiunte da TED/OC/MUR/ANAC. Ogni fonte è
uno scraper dedicato.

### Fonti prioritarie (in ordine di impatto)

#### 3.1 EU Funding & Tenders Portal — `scraper/eu_ft_scraper.py`
- URL: `https://ec.europa.eu/info/funding-tenders/opportunities/portal/`
- API: c'è (search service backend) ma non documentato; alternative HTML scraping
- Copertura: Horizon Europe, Erasmus+, EIC, Digital Europe, EU4Health, ecc.
- Volume: ~500-1.000 bandi attivi
- Effort: medio

#### 3.2 Agenzia per la Coesione Territoriale (PNRR) — `scraper/agenziacoesione_scraper.py`
- URL: `https://www.agenziacoesione.gov.it/`
- Pubblica avvisi PNRR e POR/FESR/FSE+
- Scraping HTML
- Volume: ~50-100 avvisi attivi
- Effort: medio

#### 3.3 Funzionipubbliche.gov.it / dati.gov.it — `scraper/dati_gov_it_scraper.py`
- URL: `https://www.dati.gov.it/`
- Cataloghi PA centrale, dataset di amministrazioni
- Volume: variabile
- Effort: medio

#### 3.4 InfoBandi.it — `scraper/infobandi_scraper.py`
- URL: `https://www.infobandi.it/` o aggregatori simili (notabandiitalia.it, finanziamentipubblici.it)
- Aggregatori italiani con bandi privati e regionali
- ATTENZIONE: termini di servizio possono vietare scraping. Verificare ToS.
- Volume: ~1.000-3.000 bandi attivi
- Effort: medio

#### 3.5 Portali regionali (uno per regione) — `scraper/regionali/`
- Lazio: `https://www.regione.lazio.it/cittadini/bandi-avvisi-concorsi`
- Lombardia: `https://www.regione.lombardia.it/wps/portal/istituzionale/HP/bandi`
- Emilia-Romagna: `https://bandi.regione.emilia-romagna.it/`
- Sicilia, Puglia, ecc. ognuna con HTML diverso
- Volume cumulativo: 2.000-5.000 bandi attivi
- Effort: alto (ogni regione = nuovo parser)

### Architettura per le fonti regionali

```
scraper/regionali/
  __init__.py
  base.py              # BaseRegionalScraper con parse_html() astratto
  lazio.py             # implementa parse_html per Lazio
  lombardia.py         # implementa per Lombardia
  ...
  run_all.py           # itera tutte le regioni
```

### Effort di implementazione

**Alto (10-30 ore)** per copertura completa. Realistico procedere 1-2
fonti per sessione, prioritizzando per volume/qualità.

---

## Fase 4 — Arricchire le entità

**Obiettivo**: portare il profilo delle entità da scarno a ricco, popolando i
campi oggi NULL e aggiungendo nuovi segnali.

### 4.1 ATECO + dimensione (Camera di Commercio / registroimprese)

**Problema**: i campi `entita.ateco` e `entita.dimensione` sono **sempre NULL**.
Senza ATECO le aziende non hanno settore strutturato → il matcher si basa solo
su `oc_tema` (broad) e keyword.

**Possibili fonti**:
- **registroimprese.it** API ufficiale (a pagamento, ~€0.10/visura)
- **dati.istat.it** open data: dataset ATECO con ragione sociale-CF
- **codiceateco.it** scraping (lookup per nome)
- **OpenStreetMap Overpass** per geo + tag ATECO simili (parziale)
- **PARTITA IVA REST API** open data (gratis ma limitato)

**Approccio raccomandato**: combinare due fonti:
1. **CF/PIVA → ATECO** via API InfoCamere (€) o ParteIVA REST (free, limitato)
2. **Fallback**: ricerca testuale su `codiceateco.it` con il nome dell'azienda

**Output nei segnali**: `ateco_primary` (peso 3.0), `ateco_secondary` (peso 1.0).

**Effort**: alto (3-5 ore). Costo monetario se si usa InfoCamere.

### 4.2 Descrizione testuale dai siti web aziendali

**Problema**: per aziende GitHub abbiamo `gh_description`, per quelle OC nulla.

**Approccio**:
- Per ogni azienda con `entita.sito_web` valorizzato, scaricare home + about page
- Estrarre `<title>`, `<meta description>`, primi 2 paragrafi del body
- Salvare come segnale `web_description`

**Tooling**: `requests` + `BeautifulSoup` (già nelle dipendenze).

**Volume**: ~200 aziende oggi hanno sito_web.

**Effort**: medio (2-3 ore).

### 4.3 Pubblicazioni recenti OpenAlex

**Problema**: la funzione `scrape_openalex_works(entita_id, oa_author_id)` esiste
ma non è chiamata da nessuna parte. La tabella `pubblicazioni` è a 0.

**Approccio**: dopo `scrape_openalex_authors`, per ogni ricercatore importato
chiamare `scrape_openalex_works(eid, oa_id, max_works=50)`.

**Output**: tabella `pubblicazioni` popolata con ~50 paper × 55 ricercatori = ~2.750 record.

**Uso nel matcher**: i `concetti_json` delle pubblicazioni recenti potrebbero
arricchire `_concept_score` con segnale temporale (cosa il ricercatore sta
facendo ORA, non solo storicamente).

**Effort**: basso (30 minuti — solo wiring).

### 4.4 CORDIS projects → entità

**Problema**: `entity/cordis.py` ha `scrape_cordis_projects` che cerca org per
nome con LIKE — fragile, raramente trova match.

**Approccio**:
- Riscrivere matching su PIC code (eu_pic_code è già nei segnali)
- Per ogni progetto EU, salvare titolo + topic + summary come segnali
  `eu_project_title`, `eu_project_topic`

**Effort**: medio (2-3 ore).

### 4.5 GitHub repository description (singoli repo)

Oggi salviamo `gh_description` (bio org) e `github_topic` (topic dei top repo). I
**README/description** dei singoli repo sarebbero molto descrittivi.

**Approccio**: per ogni org, prendere top 5 repo, salvare `repo.description` come
segnale `gh_repo_description`.

**Effort**: basso (30 minuti) ma costoso in rate-limit GitHub (servono +5 chiamate per org).

---

## Fase 5 — Orchestrazione background

**Obiettivo**: un comando solo che lancia tutta la pipeline (scrape + match +
report + export) in modo schedulabile e tracciabile.

### Architettura

```
scripts/run_full_pipeline.py
  - logging in data/logs/run_<timestamp>.log
  - sequenza configurabile via flag:
    --bandi --entita --enrich --match --report --export
    --max-ted --max-oc --days-back ecc.
  - timing per ogni step
  - error handling: continua anche se una fonte fallisce
  - alla fine scrive data/exports/last_run.json
    {
      "started_at": "...",
      "ended_at": "...",
      "duration_sec": ...,
      "results_by_source": {
        "ted": {"new": 1234, "updated": 56, "errors": 0},
        ...
      }
    }
```

### Schedulazione su Windows

```powershell
schtasks /create /tn "BANDI Daily Scrape" /tr "python C:\Users\andre\OneDrive\Desktop\BANDI\scripts\run_full_pipeline.py" /sc daily /st 03:00 /ru SYSTEM
```

### Schedulazione su Linux

```cron
0 3 * * * cd /path/to/BANDI && /usr/bin/python scripts/run_full_pipeline.py >> data/logs/cron.log 2>&1
```

### Sincronizzazione OneDrive — attenzione

Se due PC sincronizzano la stessa cartella e schedulano entrambi il task, possono
**collidere sul DB SQLite** (lock). Possibili soluzioni:
- Schedulare solo su un PC "primary" (es. quello acceso 24/7)
- File `.lock` per evitare doppia esecuzione
- Migrare il DB fuori OneDrive (es. `C:\BANDI_DB\`) e tenere solo il codice in OneDrive

Raccomandato: **schedulare su un solo PC**, l'altro fa solo lettura/sviluppo.

### Logging strutturato

Usare la stdlib `logging` con `RotatingFileHandler`:
```python
import logging
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    "data/logs/pipeline.log",
    maxBytes=10*1024*1024, backupCount=5
)
logging.basicConfig(level=logging.INFO, handlers=[handler])
```

### Effort di implementazione

**Basso-medio (2-3 ore)**: lo script è perlopiù glue code attorno a chiamate
esistenti, più logging.

---

## Mappa fonte → segnali entità

Per chiarire cosa **deve essere disponibile** prima che un certo componente del
matcher abbia valore:

| Componente matcher | Segnale richiesto | Popolato da |
|---|---|---|
| `tipo_score` | `entita.tipo` | tutti gli scraper entità |
| `settori_score` | `oc_tema` | OC beneficiari (dettaglio multi-tema) |
| `concept_score` | `openalex_concept` | OpenAlex (autori + istituzioni) |
| `keyword_score` | nome + segnali testuali | tutti |
| `peso_score` | `oa_h_index`/`oa_citations`/`oc_n_progetti`/`gh_n_repos` | OpenAlex + OC + GitHub |
| `geo_score` | `entita.sede_regione` + `bandi.regione` | OC enrichment + backfill bandi |

**Aggiunte future** (richiede modifica match_engine):
- `ateco_score` da Fase 4.1: ATECO entità vs settori bando (mapping da fare)
- `concept_temporale` da Fase 4.3: pubblicazioni recenti come boost concept
- `storia_appalti_score` da Fase 2: cpv vinti vs CPV bando

---

## Ordine di esecuzione raccomandato

Da più immediato e sicuro a più ambizioso:

1. **Fase 5 (orchestratore base)** — *stand-alone, non rompe niente*
2. **Fase 1 (max parametri esistenti)** — *piccola modifica, run notturno*
3. **Fase 4.3 (pubblicazioni OpenAlex)** — *wiring, 30 minuti, popola pubblicazioni*
4. **Fase 4.5 (GitHub repo description)** — *piccola estensione*
5. **Fase 2 (Playwright per ANAC)** — *primo grande sblocco di valore*
6. **Fase 4.1 (ATECO)** — *richiede decisione su API a pagamento*
7. **Fase 4.2 (siti web aziendali)** — *valore medio, scraping fragile*
8. **Fase 3 (nuove fonti bandi)** — *progetto a sé, si incrementa fonte per fonte*
9. **Fase 4.4 (CORDIS projects)** — *miglioramento qualità entità EU*

---

## Rischi globali

| Rischio | Probabilità | Mitigazione |
|---|---|---|
| Rate limit API | Alto | Sleep + retry esponenziale (già implementato OC/TED) |
| Cambio HTML siti scraped | Alto (MUR, regionali) | Test settimanali nello scheduler, alert su delta sospetti |
| WAF su nuove fonti | Medio | Playwright come fallback uniforme |
| DB SQLite lock con OneDrive multi-PC | Medio | Spostare DB fuori OneDrive o lock file |
| Crescita DB oltre 1 GB | Basso (per ora) | Pruning periodico bandi scaduti, vacuum SQLite |
| Termini di servizio (InfoBandi, ecc.) | Medio | Verificare ToS prima di ogni nuova fonte aggregatrice |
| Costo InfoCamere (ATECO) | Basso | Iniziare con fonti gratuite e fallback |

---

## Note su strumenti

- **`ruflo` / claude-flow**: orchestratore di agenti AI, non scheduler. **Non
  rilevante per questa pipeline** che è classico ETL Python.
- **APScheduler / `schedule`**: alternative a Task Scheduler/cron, vivono dentro
  un processo Python permanente. Meno robusto se il processo crasha. Preferire
  Task Scheduler per affidabilità.
- **Celery / Redis Queue**: overkill per questo volume. Utili solo se in futuro
  l'utente vuole multi-utente / interfaccia web.
- **Streamlit / FastAPI**: out of scope per questa roadmap (sono UI, non
  ingestion). Possibile Fase 6 in futuro.

---

*Documento generato come deliverable della richiesta "Opzione C — Solo design".
Le fasi sono indipendenti: si può eseguire una alla volta in sessioni successive.*
