"""Parse Indian Kanoon search pages and judgment pages into domain models.

Indian Kanoon marks up judgments richly — we lean on that structure instead of
asking an LLM to rediscover it:

* `h3.docsource_main`, `h2.doc_title`, `h3.doc_author`, `h3.doc_bench`
* `p[data-structure]` — rhetorical role per paragraph (Facts, Issue, Precedent…)
* `a[href="/doc/<id>/"]` and `span.citetext[data-docid]` — links to cited
  judgments and statute sections
* `span.hidden_text` — page numbers / upload stamps (noise, removed)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from insaaf.domain import Judgment, LinkedDoc, Paragraph, Party, RhetoricalRole

_DOC_HREF = re.compile(r"^/doc(?:fragment)?/(\d+)/")
_TITLE_DATE = re.compile(r"^(?P<parties>.+?)\s+on\s+(?P<date>\d{1,2}\s+\w+,?\s+\d{4})\s*$")
_VS = re.compile(r"\s+(?:vs\.?|v\.|versus)\s+", re.IGNORECASE)
_CITETOP = re.compile(r"Cites\s*(\d+)?.*?Cited by\s*(\d+)?", re.S)
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n\s*\n+")
_PARA_ID = re.compile(r"^(?:p|pre|blockquote)_\d+$")
_COUNT = re.compile(r"(\d+)")


@dataclass(slots=True)
class SearchHit:
    doc_id: str
    title: str
    court: str | None
    cites: int | None
    cited_by: int | None
    author: str | None


@dataclass(slots=True)
class SearchPage:
    hits: list[SearchHit]
    has_next: bool
    total: int | None = None  # "Search Results 1 - 10 of 7315"


_TOTAL = re.compile(r"Search Results\s+[\d,]+\s*-\s*[\d,]+\s+of\s+([\d,]+)", re.I)


def _clean(text: str) -> str:
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANKS.sub("\n\n", text).strip()


def _int(text: str | None) -> int | None:
    if not text:
        return None
    m = _COUNT.search(text.replace(",", ""))
    return int(m.group(1)) if m else None


def parse_date(raw: str) -> date | None:
    raw = raw.replace(",", "").strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_title(title: str) -> tuple[list[Party], date | None]:
    """'A vs B And Ors on 4 August, 2023' -> ([A (petitioner), B (respondent)], 2023-08-04)."""
    parties_part, decided = title, None
    if m := _TITLE_DATE.match(title.strip()):
        parties_part, decided = m.group("parties"), parse_date(m.group("date"))
    sides = _VS.split(parties_part, maxsplit=1)
    parties: list[Party] = []
    if len(sides) == 2:
        for name, role in zip(sides, ("petitioner", "respondent"), strict=True):
            name = name.strip(" .").replace("...", "").strip()
            if name:
                parties.append(Party(name=name, role=role))
    return parties, decided


# --------------------------------------------------------------------------- search


def parse_search_page(html: str, pagenum: int = 0) -> SearchPage:
    """Parse one results page. `pagenum` is 0-based, as in Indian Kanoon URLs."""
    soup = BeautifulSoup(html, "lxml")
    hits: list[SearchHit] = []
    for art in soup.select("article.result, div.result"):
        title_a = art.select_one(".result_title a")
        if not title_a:
            continue
        doc_id = None
        for a in art.select("a[href]"):
            if m := _DOC_HREF.match(a["href"]):
                doc_id = m.group(1)
                if a["href"].startswith("/doc/"):
                    break
        if not doc_id:
            continue
        court = art.select_one(".docsource")
        cites = cited_by = None
        author = None
        for a in art.select("a.cite_tag"):
            href, text = a.get("href", ""), a.get_text(" ", strip=True)
            if "cites:" in href:
                cites = _int(text)
            elif "citedby:" in href:
                cited_by = _int(text)
            elif "authorid:" in href:
                author = text
        hits.append(
            SearchHit(
                doc_id=doc_id,
                title=title_a.get_text(" ", strip=True),
                court=court.get_text(strip=True) if court else None,
                cites=cites,
                cited_by=cited_by,
                author=author,
            )
        )
    next_marker = f"pagenum={pagenum + 1}"
    has_next = any(
        next_marker in a.get("href", "") or a.get_text(strip=True).lower() == "next"
        for a in soup.select("a[href]")
    )
    total_m = _TOTAL.search(soup.get_text(" ", strip=True))
    return SearchPage(
        hits=hits,
        has_next=has_next and bool(hits),
        total=int(total_m.group(1).replace(",", "")) if total_m else None,
    )


# --------------------------------------------------------------------------- judgment


def _heading_text(root: Tag, cls: str, prefix: str | None = None) -> str | None:
    el = root.select_one(f".{cls}")
    if not el:
        return None
    text = el.get_text(" ", strip=True)
    if prefix and text.lower().startswith(prefix.lower()):
        text = text[len(prefix) :].strip(" :")
    return text or None


def _iter_blocks(root: Tag) -> list[Tag]:
    """Paragraph-level blocks in document order (p_N / pre_N / blockquote_N)."""
    blocks = [el for el in root.find_all(["p", "pre", "blockquote"]) if _PARA_ID.match(el.get("id", ""))]
    if blocks:
        # A blockquote may wrap p_N children; keep the outermost only once.
        seen: set[int] = set()
        out: list[Tag] = []
        for el in blocks:
            if any(id(parent) in seen for parent in el.parents):
                continue
            seen.add(id(el))
            out.append(el)
        return out
    # Fallback for markup without ids (e.g. API payloads): every top-level p/pre.
    return [el for el in root.find_all(["p", "pre", "blockquote"]) if el.get_text(strip=True)]


def parse_judgment(doc_id: str, html: str, base_url: str = "https://indiankanoon.org") -> Judgment:
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one("div.judgments") or soup.body or soup

    for noise in root.select("span.hidden_text, script, style, .ad_doc, .covers form"):
        noise.decompose()

    title = _heading_text(root, "doc_title") or (soup.title.get_text(strip=True) if soup.title else doc_id)
    court = _heading_text(root, "docsource_main")
    author = _heading_text(root, "doc_author", "Author")
    bench_raw = _heading_text(root, "doc_bench", "Bench")
    bench = [b.strip() for b in re.split(r",|\band\b", bench_raw or "") if b.strip()]

    cites = cited_by = None
    covers = root.select_one(".covers")
    if covers and (m := _CITETOP.search(covers.get_text(" ", strip=True))):
        cites, cited_by = _int(m.group(1)), _int(m.group(2))

    parties, decided = parse_title(title)

    paragraphs: list[Paragraph] = []
    link_counter: Counter[str] = Counter()
    anchors: dict[str, str] = {}
    for block in _iter_blocks(root):
        linked: list[str] = []
        for el in block.select("a[href], span.citetext[data-docid]"):
            # PARTY-tagged spans cross-reference connected matters in the cause
            # title; they are not precedents and would pollute the citation graph.
            if el.get("data-sentiment") == "PARTY" or el.find_parent(attrs={"data-sentiment": "PARTY"}):
                continue
            target = el.get("data-docid")
            if not target and (m := _DOC_HREF.match(el.get("href", ""))):
                target = m.group(1)
            if not target or target == doc_id:
                continue
            linked.append(target)
            link_counter[target] += 1
            anchors.setdefault(target, _clean(el.get_text(" ", strip=True))[:200])
        text = _clean(block.get_text("\n" if block.name == "pre" else " "))
        if not text:
            continue
        paragraphs.append(
            Paragraph(
                idx=len(paragraphs),
                role=RhetoricalRole.parse(block.get("data-structure")),
                text=text,
                linked_doc_ids=list(dict.fromkeys(linked)),
            )
        )

    return Judgment(
        doc_id=doc_id,
        title=title,
        url=f"{base_url.rstrip('/')}/doc/{doc_id}/",
        court=court,
        decision_date=decided,
        author=author,
        bench=bench or ([author] if author else []),
        parties=parties,
        cites_count=cites,
        cited_by_count=cited_by,
        paragraphs=paragraphs,
        links=[LinkedDoc(doc_id=d, anchor_text=anchors.get(d, ""), count=n) for d, n in link_counter.items()],
    )


def parse_doc_header(html: str) -> tuple[str | None, str | None]:
    """Cheap (title, docsource) extraction used to resolve linked statute docs."""
    soup = BeautifulSoup(html, "lxml")
    title = soup.select_one(".doc_title")
    source = soup.select_one(".docsource_main")
    t = title.get_text(" ", strip=True) if title else (soup.title.get_text(strip=True) if soup.title else None)
    return t, source.get_text(" ", strip=True) if source else None
