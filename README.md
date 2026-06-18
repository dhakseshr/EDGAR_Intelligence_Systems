Name: R Dhaksesh

# EDGAR Intelligence System

SEC 8-K intelligence pipeline that ingests filings, extracts events with NLP + LLMs, scores materiality, generates analyst memos, and produces weekly PDF research reports.

## Stack

- **Ingestion**: SEC EDGAR REST API, httpx, BeautifulSoup
- **NLP**: spaCy, regex, GPT-4o (event extraction + classification)
- **Scoring**: Rule-based materiality engine
- **LLM**: OpenAI GPT-4o (analyst memos, thesis analysis)
- **API**: FastAPI + PostgreSQL (SQLAlchemy)
- **Reports**: Jinja2 + WeasyPrint → PDF
- **Automation**: GitHub Actions (weekly cron)

## Quickstart

```bash
cp .env.example .env   # fill in keys
pip install -r requirements.txt
python -m spacy download en_core_web_sm
psql $DATABASE_URL -f db/schema.sql
uvicorn api.main:app --reload
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ingest` | Fetch latest 8-K filings from EDGAR |
| POST | `/process/{filing_id}` | Run full pipeline on one filing |
| POST | `/process/batch` | Process all unprocessed filings |
| GET | `/filings` | List filings with materiality scores |
| GET | `/filings/{id}/memo` | Get analyst memo + thesis impact |
| POST | `/reports/generate` | Generate weekly PDF report |

## Architecture

```
EDGAR API → ingestion → PostgreSQL
                ↓
         event_extractor (spaCy + regex + GPT-4o)
                ↓
         materiality_scorer
                ↓
         memo_generator (GPT-4o)
                ↓
         thesis_analyzer (GPT-4o)
                ↓
         report_generator (Jinja2 + WeasyPrint) → PDF
```

## GitHub Actions

Weekly report runs every Sunday at 06:00 UTC. PDF uploaded as artifact (90-day retention).
Requires `OPENAI_API_KEY` secret in repository settings.
