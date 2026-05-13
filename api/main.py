"""FastAPI application exposing the EDGAR Intelligence pipeline."""
import os
from datetime import date
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ingestion.edgar_client import EDGARClient, fetch_and_store_filings
from src.ingestion.models import Base, Filing, Company, Event, MaterialityScore, AnalystMemo
from src.extraction.event_extractor import EventExtractor
from src.scoring.materiality_scorer import MaterialityScorer
from src.llm.memo_generator import MemoGenerator
from src.analysis.thesis_analyzer import ThesisAnalyzer
from src.reporting.report_generator import generate_weekly_report

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/edgar_db")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
EDGAR_AGENT = os.getenv("EDGAR_USER_AGENT", "EDGAR Intelligence user@example.com")
REPORTS_DIR = os.getenv("REPORTS_DIR", "./reports")

engine = create_engine(DATABASE_URL.replace("+asyncpg", ""))
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="EDGAR Intelligence System", version="1.0.0")

edgar_client = EDGARClient(EDGAR_AGENT)
extractor = EventExtractor(openai_api_key=OPENAI_KEY or None, use_llm=bool(OPENAI_KEY))
scorer = MaterialityScorer()
memo_gen = MemoGenerator(api_key=OPENAI_KEY) if OPENAI_KEY else None
thesis_analyzer = ThesisAnalyzer(api_key=OPENAI_KEY) if OPENAI_KEY else None


# ── Schemas ──────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    days_back: int = 7

class ProcessFilingRequest(BaseModel):
    filing_id: str

class ReportRequest(BaseModel):
    week_start: date
    week_end: date


# ── Helpers ───────────────────────────────────────────────────────────────────

def _process_filing(filing: Filing, db):
    """Run full pipeline on a single filing."""
    from datetime import datetime

    text = filing.raw_content or ""
    items = filing.item_numbers or []

    # Event extraction
    events = extractor.extract(text, items)
    for ev in events:
        db.add(Event(
            filing_id=filing.id,
            event_type=ev["event_type"],
            summary=ev["summary"],
            confidence=ev["confidence"],
            created_at=datetime.utcnow(),
        ))

    # Materiality scoring
    has_fin = bool(text) and "$" in text
    result = scorer.score(events, text, len(text.split()), has_fin)
    db.add(MaterialityScore(
        filing_id=filing.id,
        score=result.materiality_score,
        severity=result.severity,
        breakdown=result.breakdown,
        created_at=datetime.utcnow(),
    ))

    # Memo + thesis
    memo_text = ""
    thesis_impact = "Neutral"
    thesis_conf = 0.5
    thesis_reason = ""
    if memo_gen:
        memo_text = memo_gen.generate(
            company=filing.company.name if filing.company else "Unknown",
            filing_date=str(filing.filing_date),
            events=events,
            materiality_score=result.materiality_score,
            severity=result.severity,
            text=text,
        )
    if thesis_analyzer:
        thesis = thesis_analyzer.analyze(
            company=filing.company.name if filing.company else "Unknown",
            events=events,
            materiality_score=result.materiality_score,
            severity=result.severity,
            memo=memo_text,
        )
    else:
        from src.analysis.thesis_analyzer import ThesisAnalyzer as TA
        thesis = TA("").rule_based_fallback(events, result.materiality_score, result.severity)

    thesis_impact = thesis["thesis_impact"]
    thesis_conf = thesis["confidence"]
    thesis_reason = thesis["reasoning"]

    db.add(AnalystMemo(
        filing_id=filing.id,
        content=memo_text,
        thesis_impact=thesis_impact,
        thesis_confidence=thesis_conf,
        thesis_reasoning=thesis_reason,
        created_at=datetime.utcnow(),
    ))

    filing.processed = True
    db.commit()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest")
async def ingest_filings(req: IngestRequest, background_tasks: BackgroundTasks):
    """Fetch and store recent 8-K filings from EDGAR."""
    import asyncio
    db = SessionLocal()
    try:
        await fetch_and_store_filings(edgar_client, db, days_back=req.days_back)
        count = db.query(Filing).filter_by(processed=False).count()
    finally:
        db.close()
    return {"message": "Ingestion complete", "unprocessed_filings": count}


@app.post("/process/{filing_id}")
def process_filing(filing_id: str):
    """Run NLP + LLM pipeline on a single filing."""
    db = SessionLocal()
    try:
        filing = db.query(Filing).filter_by(id=filing_id).first()
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        _process_filing(filing, db)
        return {"message": "Processing complete", "filing_id": filing_id}
    finally:
        db.close()


@app.post("/process/batch")
def process_all_unprocessed():
    """Process all unprocessed filings."""
    db = SessionLocal()
    try:
        filings = db.query(Filing).filter_by(processed=False).all()
        for f in filings:
            _process_filing(f, db)
        return {"processed": len(filings)}
    finally:
        db.close()


@app.get("/filings")
def list_filings(
    limit: int = Query(50, le=200),
    offset: int = 0,
    severity: Optional[str] = None,
):
    db = SessionLocal()
    try:
        q = db.query(Filing, Company, MaterialityScore).join(
            Company, Filing.company_id == Company.id, isouter=True
        ).join(
            MaterialityScore, MaterialityScore.filing_id == Filing.id, isouter=True
        )
        if severity:
            q = q.filter(MaterialityScore.severity == severity)
        q = q.order_by(Filing.filing_date.desc()).offset(offset).limit(limit)
        rows = q.all()
        result = []
        for filing, company, ms in rows:
            result.append({
                "id": str(filing.id),
                "company": company.name if company else "",
                "ticker": company.ticker if company else "",
                "filing_date": str(filing.filing_date),
                "items": filing.item_numbers,
                "url": filing.filing_url,
                "score": ms.score if ms else None,
                "severity": ms.severity if ms else None,
                "processed": filing.processed,
            })
        return result
    finally:
        db.close()


@app.get("/filings/{filing_id}/memo")
def get_memo(filing_id: str):
    db = SessionLocal()
    try:
        memo = db.query(AnalystMemo).filter_by(filing_id=filing_id).first()
        if not memo:
            raise HTTPException(status_code=404, detail="Memo not found")
        return {
            "content": memo.content,
            "thesis_impact": memo.thesis_impact,
            "thesis_confidence": memo.thesis_confidence,
            "thesis_reasoning": memo.thesis_reasoning,
        }
    finally:
        db.close()


@app.post("/reports/generate")
def generate_report(req: ReportRequest):
    """Generate weekly PDF report for a date range."""
    db = SessionLocal()
    try:
        filings_data = []
        rows = (
            db.query(Filing, Company, MaterialityScore, AnalystMemo)
            .join(Company, Filing.company_id == Company.id, isouter=True)
            .join(MaterialityScore, MaterialityScore.filing_id == Filing.id, isouter=True)
            .join(AnalystMemo, AnalystMemo.filing_id == Filing.id, isouter=True)
            .filter(Filing.filing_date.between(req.week_start, req.week_end))
            .order_by(MaterialityScore.score.desc())
            .all()
        )
        for filing, company, ms, memo in rows:
            events = [
                {"event_type": e.event_type, "summary": e.summary, "confidence": e.confidence}
                for e in filing.events
            ]
            filings_data.append({
                "company": company.name if company else "Unknown",
                "filing_date": str(filing.filing_date),
                "sector": company.sector if company and company.sector else "General",
                "score": ms.score if ms else 0,
                "severity": ms.severity if ms else "Low",
                "thesis": memo.thesis_impact if memo else "Neutral",
                "thesis_confidence": memo.thesis_confidence if memo else 0.5,
                "thesis_reasoning": memo.thesis_reasoning if memo else "",
                "key_factors": [],
                "events": events,
                "memo": memo.content if memo else "",
            })

        fname = f"edgar_report_{req.week_start}_{req.week_end}.pdf"
        out_path = os.path.join(REPORTS_DIR, fname)
        path = generate_weekly_report(filings_data, req.week_start, req.week_end, out_path)
        return FileResponse(path, media_type="application/pdf", filename=fname)
    finally:
        db.close()
