"""LLM-powered analyst memo generator."""
import json
from typing import Optional
from openai import OpenAI

MEMO_SYSTEM_PROMPT = """You are a senior sell-side equity research analyst at a top-tier investment bank.
Your memos are clear, precise, and actionable. You write in professional financial prose.
Do not use filler language. Be direct and specific."""

MEMO_USER_PROMPT = """Generate an analyst memo for the following SEC 8-K filing.

Company: {company}
Filing Date: {filing_date}
Detected Events: {events}
Materiality Score: {score}/100 ({severity})
Filing Excerpt:
{text}

Write the memo in Markdown with these exact sections:
## Executive Summary
(2-3 sentences capturing the most important development)

## Key Events
(Bullet list of extracted events with brief analysis)

## Potential Risks
(Bullet list of material downside risks)

## Potential Opportunities
(Bullet list of upside catalysts or positive implications)

## Sector Impact
(How this filing may affect the broader sector or peers)

## Investment Thesis Impact
(How this changes or reinforces the investment thesis; be direct)
"""


class MemoGenerator:
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate(
        self,
        company: str,
        filing_date: str,
        events: list[dict],
        materiality_score: int,
        severity: str,
        text: str,
    ) -> str:
        events_str = json.dumps(events, indent=2)
        user_msg = MEMO_USER_PROMPT.format(
            company=company,
            filing_date=filing_date,
            events=events_str,
            score=materiality_score,
            severity=severity,
            text=text[:3000],
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": MEMO_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        return resp.choices[0].message.content.strip()

    def generate_batch(self, filings_data: list[dict]) -> list[str]:
        """Generate memos for multiple filings."""
        return [self.generate(**f) for f in filings_data]
