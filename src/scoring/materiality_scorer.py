"""Materiality scoring engine for SEC 8-K filings."""
import re
from dataclasses import dataclass

# Weights must sum to 100
EVENT_TYPE_SCORES = {
    "Bankruptcy": 35,
    "Acquisition": 30,
    "Litigation": 20,
    "Executive Change": 15,
    "Earnings Announcement": 15,
    "Share Buyback": 10,
    "Partnership": 10,
    "Product Launch": 8,
    "Other": 3,
}

SEVERITY_THRESHOLDS = [
    (80, "Critical"),
    (55, "High"),
    (30, "Medium"),
    (0,  "Low"),
]


@dataclass
class ScoringResult:
    materiality_score: int
    severity: str
    breakdown: dict


class MaterialityScorer:
    """
    Score formula (0–100):
      event_type_score   : up to 35  (highest event type score among detected events)
      financial_figures  : up to 20  (presence + magnitude of $ amounts)
      document_length    : up to 15  (proxy for significance; very short = routine)
      management_change  : up to 20  (executive change event present)
      strategic_keywords : up to 10  (M&A / strategic / material keywords)
    Total max: 100
    """

    def score(self, events: list[dict], text: str, word_count: int, has_financial_figures: bool) -> ScoringResult:
        breakdown = {}

        # 1. Event type score (max 35)
        type_scores = [EVENT_TYPE_SCORES.get(e["event_type"], 3) for e in events]
        event_score = min(35, max(type_scores, default=0))
        breakdown["event_type"] = event_score

        # 2. Financial figures (max 20)
        fin_score = 0
        if has_financial_figures:
            fin_score = 12
            # Bonus for large figures (billion-scale)
            if re.search(r"\$[\d,.]+\s*billion", text, re.I):
                fin_score = 20
            elif re.search(r"\$[\d,.]+\s*million", text, re.I):
                fin_score = 16
        breakdown["financial_figures"] = fin_score

        # 3. Document length (max 15)
        if word_count > 2000:
            doc_score = 15
        elif word_count > 800:
            doc_score = 10
        elif word_count > 200:
            doc_score = 5
        else:
            doc_score = 2
        breakdown["document_length"] = doc_score

        # 4. Management change (max 20)
        mgmt_score = 0
        mgmt_events = [e for e in events if e["event_type"] == "Executive Change"]
        if mgmt_events:
            best_conf = max(e["confidence"] for e in mgmt_events)
            mgmt_score = int(20 * best_conf)
        breakdown["management_change"] = mgmt_score

        # 5. Strategic keywords (max 10)
        strategic_terms = [
            "material", "strategic", "transformative", "significant", "landmark",
            "definitive agreement", "merger", "acquisition", "spin-off",
        ]
        strat_hits = sum(1 for term in strategic_terms if re.search(term, text, re.I))
        strat_score = min(10, strat_hits * 2)
        breakdown["strategic_keywords"] = strat_score

        total = event_score + fin_score + doc_score + mgmt_score + strat_score
        total = max(0, min(100, total))

        severity = "Low"
        for threshold, label in SEVERITY_THRESHOLDS:
            if total >= threshold:
                severity = label
                break

        return ScoringResult(
            materiality_score=total,
            severity=severity,
            breakdown=breakdown,
        )
