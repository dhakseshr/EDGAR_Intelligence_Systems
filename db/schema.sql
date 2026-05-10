CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker VARCHAR(10) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    cik VARCHAR(20),
    sector VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS filings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(id),
    accession_number VARCHAR(50) UNIQUE NOT NULL,
    filing_date DATE NOT NULL,
    form_type VARCHAR(20) DEFAULT '8-K',
    filing_url TEXT,
    raw_content TEXT,
    item_numbers TEXT[],
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filing_id UUID REFERENCES filings(id),
    event_type VARCHAR(100) NOT NULL,
    summary TEXT,
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS materiality_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filing_id UUID REFERENCES filings(id) UNIQUE,
    score INTEGER CHECK (score BETWEEN 0 AND 100),
    severity VARCHAR(20) CHECK (severity IN ('Low','Medium','High','Critical')),
    breakdown JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analyst_memos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filing_id UUID REFERENCES filings(id) UNIQUE,
    content TEXT,
    thesis_impact VARCHAR(20) CHECK (thesis_impact IN ('Bullish','Neutral','Bearish')),
    thesis_confidence FLOAT,
    thesis_reasoning TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS weekly_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    pdf_path TEXT,
    filing_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_filings_date ON filings(filing_date);
CREATE INDEX idx_filings_company ON filings(company_id);
CREATE INDEX idx_events_filing ON events(filing_id);
CREATE INDEX idx_events_type ON events(event_type);
