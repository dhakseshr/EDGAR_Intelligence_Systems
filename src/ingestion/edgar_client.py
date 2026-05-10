"""SEC EDGAR API client for fetching 8-K filings."""
import re
import asyncio
from datetime import date, timedelta
from typing import Optional
import httpx
from bs4 import BeautifulSoup

EDGAR_BASE = "https://data.sec.gov"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"


class EDGARClient:
    def __init__(self, user_agent: str):
        self.headers = {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
        }

    async def get_recent_8k_filings(
        self,
        days_back: int = 7,
        max_results: int = 100,
    ) -> list[dict]:
        """Fetch recent 8-K filings from EDGAR full-text search."""
        date_from = (date.today() - timedelta(days=days_back)).isoformat()
        params = {
            "q": '"8-K"',
            "dateRange": "custom",
            "startdt": date_from,
            "enddt": date.today().isoformat(),
            "forms": "8-K",
            "_source": "file_date,entity_name,file_num,period_of_report,form_type",
            "from": 0,
            "size": max_results,
        }
        async with httpx.AsyncClient(headers=self.headers, timeout=30) as client:
            resp = await client.get(
                "https://efts.sec.gov/LATEST/search-index",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        return [self._parse_search_hit(h) for h in hits]

    def _parse_search_hit(self, hit: dict) -> dict:
        src = hit.get("_source", {})
        accession = hit.get("_id", "").replace(":", "-")
        cik = hit.get("_id", "").split(":")[0] if ":" in hit.get("_id", "") else ""
        return {
            "accession_number": accession,
            "cik": cik,
            "company_name": src.get("entity_name", ""),
            "filing_date": src.get("file_date", ""),
            "form_type": src.get("form_type", "8-K"),
            "filing_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm",
        }

    async def get_company_submissions(self, cik: str) -> dict:
        """Fetch company submissions from EDGAR."""
        cik_padded = cik.zfill(10)
        url = f"{EDGAR_SUBMISSIONS}/CIK{cik_padded}.json"
        async with httpx.AsyncClient(headers=self.headers, timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def get_ticker_to_cik_map(self) -> dict[str, str]:
        """Return ticker → CIK mapping from EDGAR company_tickers.json."""
        url = f"{EDGAR_BASE}/files/company_tickers.json"
        async with httpx.AsyncClient(headers=self.headers, timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        return {v["ticker"]: str(v["cik_str"]) for v in data.values()}

    async def download_filing_document(self, accession_number: str, cik: str) -> str:
        """Download and return the primary HTML document of a filing."""
        acc_clean = accession_number.replace("-", "")
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{accession_number}-index.htm"
        async with httpx.AsyncClient(headers=self.headers, timeout=60, follow_redirects=True) as client:
            try:
                resp = await client.get(index_url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                doc_url = self._find_primary_doc(soup, cik, acc_clean)
                if doc_url:
                    doc_resp = await client.get(doc_url)
                    doc_resp.raise_for_status()
                    return doc_resp.text
            except httpx.HTTPError:
                return ""
        return ""

    def _find_primary_doc(self, soup: BeautifulSoup, cik: str, acc_clean: str) -> Optional[str]:
        """Find the primary 8-K document URL from filing index."""
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) >= 4:
                doc_type = cells[3].get_text(strip=True)
                if doc_type in ("8-K", "8-K/A"):
                    link = cells[2].find("a")
                    if link and link.get("href"):
                        href = link["href"]
                        if not href.startswith("http"):
                            href = f"https://www.sec.gov{href}"
                        return href
        # Fallback: first .htm link
        for a in soup.select("a[href]"):
            href = a["href"]
            if href.endswith(".htm") and acc_clean in href:
                if not href.startswith("http"):
                    href = f"https://www.sec.gov{href}"
                return href
        return None

    def parse_filing_content(self, html: str) -> dict:
        """Extract metadata from 8-K HTML content."""
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(separator=" ", strip=True)
        item_numbers = self._extract_items(text)
        return {
            "text": text[:50000],  # cap at 50k chars
            "item_numbers": item_numbers,
            "has_financial_figures": bool(re.search(r"\$[\d,]+(?:\.\d+)?(?:\s*(?:million|billion))?", text, re.I)),
            "word_count": len(text.split()),
        }

    def _extract_items(self, text: str) -> list[str]:
        """Extract Item numbers referenced in filing."""
        matches = re.findall(r"Item\s+(\d+\.\d+)", text, re.I)
        return list(dict.fromkeys(matches))  # deduplicated


async def fetch_and_store_filings(client: EDGARClient, db_session, days_back: int = 7):
    """Orchestrate fetching filings and persisting to DB."""
    from datetime import datetime
    from src.ingestion.models import Company, Filing

    filings_meta = await client.get_recent_8k_filings(days_back=days_back)

    for meta in filings_meta:
        # Upsert company
        company = db_session.query(Company).filter_by(name=meta["company_name"]).first()
        if not company:
            company = Company(
                name=meta["company_name"],
                cik=meta["cik"],
                ticker=meta.get("ticker", meta["cik"]),
            )
            db_session.add(company)
            db_session.flush()

        # Skip duplicate filings
        existing = db_session.query(Filing).filter_by(
            accession_number=meta["accession_number"]
        ).first()
        if existing:
            continue

        # Download and parse document
        html = await client.download_filing_document(meta["accession_number"], meta["cik"])
        parsed = client.parse_filing_content(html) if html else {"text": "", "item_numbers": [], "word_count": 0}

        filing = Filing(
            company_id=company.id,
            accession_number=meta["accession_number"],
            filing_date=date.fromisoformat(meta["filing_date"]) if meta["filing_date"] else date.today(),
            form_type=meta["form_type"],
            filing_url=meta["filing_url"],
            raw_content=parsed["text"],
            item_numbers=parsed["item_numbers"],
            processed=False,
            created_at=datetime.utcnow(),
        )
        db_session.add(filing)

    db_session.commit()
