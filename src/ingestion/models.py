from sqlalchemy import Column, String, Boolean, Date, Text, Float, Integer, ARRAY, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ
from sqlalchemy.orm import declarative_base, relationship
import uuid

Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker = Column(String(10), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    cik = Column(String(20))
    sector = Column(String(100))
    created_at = Column(TIMESTAMPTZ)
    filings = relationship("Filing", back_populates="company")


class Filing(Base):
    __tablename__ = "filings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"))
    accession_number = Column(String(50), unique=True, nullable=False)
    filing_date = Column(Date, nullable=False)
    form_type = Column(String(20), default="8-K")
    filing_url = Column(Text)
    raw_content = Column(Text)
    item_numbers = Column(ARRAY(Text))
    processed = Column(Boolean, default=False)
    created_at = Column(TIMESTAMPTZ)
    company = relationship("Company", back_populates="filings")
    events = relationship("Event", back_populates="filing")
    materiality = relationship("MaterialityScore", back_populates="filing", uselist=False)
    memo = relationship("AnalystMemo", back_populates="filing", uselist=False)


class Event(Base):
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filing_id = Column(UUID(as_uuid=True), ForeignKey("filings.id"))
    event_type = Column(String(100), nullable=False)
    summary = Column(Text)
    confidence = Column(Float)
    created_at = Column(TIMESTAMPTZ)
    filing = relationship("Filing", back_populates="events")


class MaterialityScore(Base):
    __tablename__ = "materiality_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filing_id = Column(UUID(as_uuid=True), ForeignKey("filings.id"), unique=True)
    score = Column(Integer)
    severity = Column(String(20))
    breakdown = Column(JSONB)
    created_at = Column(TIMESTAMPTZ)
    filing = relationship("Filing", back_populates="materiality")


class AnalystMemo(Base):
    __tablename__ = "analyst_memos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filing_id = Column(UUID(as_uuid=True), ForeignKey("filings.id"), unique=True)
    content = Column(Text)
    thesis_impact = Column(String(20))
    thesis_confidence = Column(Float)
    thesis_reasoning = Column(Text)
    created_at = Column(TIMESTAMPTZ)
    filing = relationship("Filing", back_populates="memo")
