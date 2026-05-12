"""Thesis impact analyzer: determines Bullish / Neutral / Bearish stance."""
import json
from openai import OpenAI

THESIS_PROMPT = """You are a quantitative equity research analyst.

Based on the following SEC 8-K filing data, determine the investment thesis impact.

Company: {company}
Events detected: {events}
Materiality Score: {score}/100 ({severity})
Analyst memo excerpt:
{memo}

Return ONLY a valid JSON object (no markdown, no explanation) with this exact structure:
{{
  "thesis_impact": "Bullish" | "Neutral" | "Bearish",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<2-3 sentence explanation>",
  "key_factors": ["<factor1>", "<factor2>", "<factor3>"]
}}
"""


class ThesisAnalyzer:
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def analyze(
        self,
        company: str,
        events: list[dict],
        materiality_score: int,
        severity: str,
        memo: str,
    ) -> dict:
        prompt = THESIS_PROMPT.format(
            company=company,
            events=json.dumps(events, indent=2),
            score=materiality_score,
            severity=severity,
            memo=memo[:1500],
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)
        # Validate and normalise
        impact = data.get("thesis_impact", "Neutral")
        if impact not in ("Bullish", "Neutral", "Bearish"):
            impact = "Neutral"
        return {
            "thesis_impact": impact,
            "confidence": round(float(data.get("confidence", 0.5)), 3),
            "reasoning": data.get("reasoning", ""),
            "key_factors": data.get("key_factors", []),
        }

    def rule_based_fallback(self, events: list[dict], materiality_score: int, severity: str) -> dict:
        """Deterministic fallback when LLM is unavailable."""
        bearish_events = {"Bankruptcy", "Litigation"}
        bullish_events = {"Acquisition", "Earnings Announcement", "Share Buyback", "Product Launch"}

        event_types = {e["event_type"] for e in events}
        bearish_hits = len(event_types & bearish_events)
        bullish_hits = len(event_types & bullish_events)

        if bearish_hits > bullish_hits or severity == "Critical":
            impact, conf = "Bearish", 0.65
        elif bullish_hits > bearish_hits and materiality_score > 40:
            impact, conf = "Bullish", 0.60
        else:
            impact, conf = "Neutral", 0.55

        return {
            "thesis_impact": impact,
            "confidence": conf,
            "reasoning": f"Rule-based: detected {event_types}. Materiality {materiality_score}/100.",
            "key_factors": list(event_types),
        }
