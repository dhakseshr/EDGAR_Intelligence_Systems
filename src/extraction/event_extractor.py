"""NLP event extraction pipeline using spaCy, regex, and LLM classification."""
import re
import json
from dataclasses import dataclass
from typing import Optional
import spacy
from openai import OpenAI

EVENT_PATTERNS: dict[str, list[str]] = {
    "Acquisition": [
        r"\b(?:acqui(?:re|sition)|merger|purchase[sd]?\s+(?:all|assets|business)|definitive\s+agreement\s+to\s+(?:acquire|merge))\b",
    ],
    "Executive Change": [
        r"\b(?:appoint(?:ed|ment)|resign(?:ed|ation)|CEO|CFO|CTO|COO|Chief\s+(?:Executive|Financial|Operating|Technology)\s+Officer|President|director)\b.*\b(?:step(?:ping)?\s+down|resign|retire|appoint|named|elected|hired)\b",
        r"\b(?:resign|retire|step(?:ping)?\s+down|named|appointed|elected|hired)\b.{0,80}\b(?:CEO|CFO|CTO|COO|President|Chief)\b",
    ],
    "Partnership": [
        r"\b(?:partnership|collaboration|joint\s+venture|strategic\s+alliance|agreement\s+with|collaboration\s+with|partner(?:ed|ing)\s+with)\b",
    ],
    "Product Launch": [
        r"\b(?:launch(?:ed|ing)?|introduc(?:ed|ing)|announc(?:ed|ing)\s+(?:new|the\s+launch)|commerciali[sz](?:ed|ing)|debut(?:ed|ing)?)\b.{0,80}\b(?:product|platform|solution|service|technology|software)\b",
    ],
    "Litigation": [
        r"\b(?:lawsuit|litigation|legal\s+proceeding|complaint\s+filed|class\s+action|arbitration|settlement|court|jury\s+verdict|indictment|SEC\s+investigation)\b",
    ],
    "Bankruptcy": [
        r"\b(?:chapter\s+(?:7|11|13)|bankrupt(?:cy)?|insolvency|receivership|restructuring\s+plan|debt\s+restructur|going\s+concern)\b",
    ],
    "Share Buyback": [
        r"\b(?:share\s+repurchase|stock\s+buyback|repurchase\s+program|buyback\s+program|repurchas(?:ed|ing)\s+(?:up\s+to\s+)?[\$\d])\b",
    ],
    "Earnings Announcement": [
        r"\b(?:earnings?\s+(?:release|results?|announcement)|quarterly\s+(?:results?|earnings?)|fiscal\s+(?:year|quarter)\s+results?|EPS|revenue\s+(?:increased|decreased|grew|fell)|net\s+income)\b",
    ],
}

ITEM_TO_EVENT = {
    "1.01": "Partnership",
    "1.02": "Partnership",
    "1.03": "Bankruptcy",
    "2.01": "Acquisition",
    "2.02": "Earnings Announcement",
    "2.06": "Earnings Announcement",
    "3.01": None,
    "5.01": "Executive Change",
    "5.02": "Executive Change",
    "7.01": None,
    "8.01": None,
}

LLM_CLASSIFICATION_PROMPT = """You are a financial analyst. Classify the following SEC 8-K filing excerpt into one or more event types.

Event types: Acquisition, Executive Change, Partnership, Product Launch, Litigation, Bankruptcy, Share Buyback, Earnings Announcement, Other

Filing text:
{text}

Item numbers referenced: {items}

Return a JSON array of objects. Each object must have:
- event_type: string (one of the types above)
- summary: string (1-2 sentence description)
- confidence: float (0.0-1.0)

Return only valid JSON, no markdown.
"""


@dataclass
class ExtractedEvent:
    event_type: str
    summary: str
    confidence: float


class EventExtractor:
    def __init__(self, openai_api_key: Optional[str] = None, use_llm: bool = True):
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            self.nlp = None
        self.use_llm = use_llm and openai_api_key
        self.llm_client = OpenAI(api_key=openai_api_key) if openai_api_key else None

    def extract(self, text: str, item_numbers: list[str] = None) -> list[dict]:
        """Run full extraction pipeline: regex → spaCy → LLM."""
        item_numbers = item_numbers or []
        events: list[ExtractedEvent] = []

        # Stage 1: item number hints
        for item in item_numbers:
            mapped = ITEM_TO_EVENT.get(item)
            if mapped:
                events.append(ExtractedEvent(
                    event_type=mapped,
                    summary=f"Filing references Item {item}",
                    confidence=0.6,
                ))

        # Stage 2: regex patterns
        sample = text[:10000]
        for event_type, patterns in EVENT_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, sample, re.I | re.DOTALL)
                if match:
                    start = max(0, match.start() - 50)
                    end = min(len(sample), match.end() + 150)
                    snippet = sample[start:end].strip()
                    # Update confidence if already found via item hints
                    existing = next((e for e in events if e.event_type == event_type), None)
                    if existing:
                        existing.confidence = min(0.95, existing.confidence + 0.2)
                        existing.summary = snippet[:200]
                    else:
                        events.append(ExtractedEvent(
                            event_type=event_type,
                            summary=snippet[:200],
                            confidence=0.75,
                        ))
                    break

        # Stage 3: spaCy org/person NER for executive changes
        if self.nlp and text:
            doc = self.nlp(text[:5000])
            persons = [ent.text for ent in doc.ents if ent.label_ == "PERSON"]
            if persons:
                exec_event = next((e for e in events if e.event_type == "Executive Change"), None)
                if exec_event:
                    exec_event.summary = f"Persons mentioned: {', '.join(persons[:3])}. {exec_event.summary}"

        # Stage 4: LLM classification
        if self.use_llm and self.llm_client and text:
            llm_events = self._llm_classify(text[:4000], item_numbers)
            # Merge LLM results, preferring higher confidence
            for le in llm_events:
                existing = next((e for e in events if e.event_type == le.event_type), None)
                if existing:
                    if le.confidence > existing.confidence:
                        existing.confidence = le.confidence
                        existing.summary = le.summary
                else:
                    events.append(le)

        return [{"event_type": e.event_type, "summary": e.summary, "confidence": round(e.confidence, 3)} for e in events]

    def _llm_classify(self, text: str, item_numbers: list[str]) -> list[ExtractedEvent]:
        prompt = LLM_CLASSIFICATION_PROMPT.format(
            text=text,
            items=", ".join(item_numbers) if item_numbers else "none",
        )
        try:
            resp = self.llm_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=800,
            )
            raw = resp.choices[0].message.content.strip()
            data = json.loads(raw)
            return [
                ExtractedEvent(
                    event_type=item.get("event_type", "Other"),
                    summary=item.get("summary", ""),
                    confidence=float(item.get("confidence", 0.5)),
                )
                for item in data
                if isinstance(item, dict)
            ]
        except Exception:
            return []
