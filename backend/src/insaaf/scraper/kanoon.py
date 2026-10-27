"""Indian Kanoon source: discovery (search) and document fetching.

Two transports:
* HTML (default) — the public website, politely rate-limited, robots.txt honoured.
* Official API (api.indiankanoon.org) — used automatically when
  KANOON_API_TOKEN is set; faster and the preferred route for bulk ingestion.
"""

from __future__ import annotations

import calendar
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from urllib.parse import quote

from insaaf.config import Settings
from insaaf.logs import log
from insaaf.scraper.http import PoliteClient
from insaaf.scraper.parser import SearchHit, SearchPage, parse_search_page

RESULTS_PER_PAGE = 10
DEFAULT_PAGE_CAP = 40  # Indian Kanoon stops paginating around here


@dataclass(slots=True, frozen=True)
class Window:
    start: date
    end: date

    def query_fragment(self) -> str:
        f = lambda d: f"{d.day}-{d.month}-{d.year}"  # noqa: E731
        return f"fromdate:{f(self.start)} todate:{f(self.end)}"

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def split(self) -> tuple[Window, Window]:
        mid = self.start + timedelta(days=self.days // 2 - 1)
        return Window(self.start, mid), Window(mid + timedelta(days=1), self.end)


def month_windows(year_from: int, year_to: int) -> list[Window]:
    out = []
    for y in range(year_from, year_to + 1):
        for m in range(1, 13):
            last = calendar.monthrange(y, m)[1]
            out.append(Window(date(y, m, 1), date(y, m, last)))
    return out


class KanoonSource:
    def __init__(self, settings: Settings, page_cap: int = DEFAULT_PAGE_CAP) -> None:
        self.s = settings
        self.page_cap = page_cap
        self.api_mode = settings.kanoon_api_token is not None
        if self.api_mode:
            token = settings.kanoon_api_token.get_secret_value()  # type: ignore[union-attr]
            self.http = PoliteClient(
                "https://api.indiankanoon.org",
                settings.scraper_user_agent,
                rate_per_s=max(settings.scraper_rate_per_s, 2.0),
                max_retries=settings.scraper_max_retries,
                respect_robots=False,
                headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            )
        else:
            self.http = PoliteClient(
                settings.kanoon_base_url,
                settings.scraper_user_agent,
                rate_per_s=settings.scraper_rate_per_s,
                max_retries=settings.scraper_max_retries,
                respect_robots=settings.scraper_respect_robots,
            )

    async def aclose(self) -> None:
        await self.http.aclose()

    # ------------------------------------------------------------------ search

    async def search_page(self, query: str, pagenum: int) -> SearchPage:
        if self.api_mode:
            resp = await self.http.request(
                "POST", f"/search/?formInput={quote(query)}&pagenum={pagenum}"
            )
            data = resp.json()
            hits = [
                SearchHit(
                    doc_id=str(d["tid"]),
                    title=d.get("title", ""),
                    court=d.get("docsource"),
                    cites=d.get("numcites"),
                    cited_by=d.get("numcitedby"),
                    author=d.get("author"),
                )
                for d in data.get("docs", [])
            ]
            total = data.get("found")
            total_int = int(str(total).split()[0].replace(",", "")) if total else None
            return SearchPage(hits=hits, has_next=len(hits) >= RESULTS_PER_PAGE, total=total_int)

        html = await self.http.get_text(f"/search/?formInput={quote(query)}&pagenum={pagenum}")
        return parse_search_page(html, pagenum)

    async def iter_query(self, query: str) -> AsyncIterator[SearchHit]:
        for pagenum in range(self.page_cap):
            page = await self.search_page(query, pagenum)
            for hit in page.hits:
                yield hit
            if not page.has_next:
                return

    async def discover(
        self, base_query: str, windows: list[Window]
    ) -> AsyncIterator[tuple[Window, SearchHit]]:
        """Walk date windows, recursively splitting any window whose result
        count exceeds what pagination can reach."""
        reachable = self.page_cap * RESULTS_PER_PAGE
        stack = list(reversed(windows))
        while stack:
            w = stack.pop()
            query = f"{base_query} {w.query_fragment()}".strip()
            first = await self.search_page(query, 0)
            total = first.total or 0
            if total > reachable and w.days > 1:
                left, right = w.split()
                stack.extend([right, left])
                continue
            if total > reachable:
                log.warning(
                    "discover.truncated",
                    window=str(w.start),
                    total=total,
                    reachable=reachable,
                    hint="narrow the base query (e.g. add a topic) for full coverage",
                )
            log.info("discover.window", start=str(w.start), end=str(w.end), total=total)
            for hit in first.hits:
                yield w, hit
            if not first.has_next:
                continue
            for pagenum in range(1, self.page_cap):
                page = await self.search_page(query, pagenum)
                for hit in page.hits:
                    yield w, hit
                if not page.has_next:
                    break

    # ------------------------------------------------------------------ documents

    async def fetch_doc_html(self, doc_id: str) -> str:
        if self.api_mode:
            data = (await self.http.request("POST", f"/doc/{doc_id}/")).json()
            # Normalise the API payload into the same shape as the website.
            return (
                '<div class="judgments">'
                f'<h3 class="docsource_main">{escape(data.get("docsource", ""))}</h3>'
                f'<h2 class="doc_title">{escape(data.get("title", ""))}</h2>'
                f"{data.get('doc', '')}</div>"
            )
        return await self.http.get_text(f"/doc/{doc_id}/")
