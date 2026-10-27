from datetime import date

from insaaf.domain import RhetoricalRole
from insaaf.scraper.kanoon import Window, month_windows
from insaaf.scraper.parser import parse_judgment, parse_search_page, parse_title


def test_parse_judgment_metadata(judgment_html: str) -> None:
    j = parse_judgment("111", judgment_html)
    assert j.title == "Ramesh Kumar vs The State Of Maharashtra on 12 March, 2023"
    assert j.court == "Bombay High Court"
    assert j.decision_date == date(2023, 3, 12)
    assert j.author == "A. B. Judge"
    assert j.bench == ["A. B. Judge", "C. D. Judge"]
    assert j.cites_count == 4 and j.cited_by_count == 27
    assert [(p.name, p.role) for p in j.parties] == [
        ("Ramesh Kumar", "petitioner"),
        ("The State Of Maharashtra", "respondent"),
    ]
    assert j.url == "https://indiankanoon.org/doc/111/"


def test_parse_judgment_paragraphs_and_roles(judgment_html: str) -> None:
    j = parse_judgment("111", judgment_html)
    roles = [p.role for p in j.paragraphs]
    # pre block + 5 non-empty paragraphs (empty CDiscource paragraph dropped)
    assert len(j.paragraphs) == 6
    assert roles[1:] == [
        RhetoricalRole.FACTS,
        RhetoricalRole.ISSUE,
        RhetoricalRole.PRECEDENT,
        RhetoricalRole.SECTION,
        RhetoricalRole.CONCLUSION,
    ]
    assert [p.idx for p in j.paragraphs] == list(range(6))
    # hidden page-number noise removed
    assert "Page 1/5" not in j.full_text


def test_parse_judgment_links(judgment_html: str) -> None:
    j = parse_judgment("111", judgment_html)
    ids = {link.doc_id for link in j.links}
    assert ids == {"1560742", "1897847", "222", "333"}  # self-link 111 excluded
    anchors = {link.doc_id: link.anchor_text for link in j.links}
    assert anchors["1897847"] == "120-B"
    assert anchors["333"].startswith("Satender Kumar Antil")


def test_parse_search_page(search_html: str) -> None:
    page = parse_search_page(search_html, pagenum=0)
    assert [h.doc_id for h in page.hits] == ["111", "112"]
    assert page.hits[0].cited_by == 1027 and page.hits[0].cites == 4
    assert page.hits[0].court == "Bombay High Court"
    assert page.total == 1234
    assert page.has_next is True
    assert parse_search_page(search_html, pagenum=5).has_next is False


def test_parse_title_variants() -> None:
    parties, d = parse_title("A. Kumar v. Union Of India on 1 Jan, 2020")
    assert [p.name for p in parties] == ["A. Kumar", "Union Of India"]
    assert d == date(2020, 1, 1)
    parties, d = parse_title("In Re: Some Reference")
    assert parties == [] and d is None


def test_windows_split_and_query() -> None:
    windows = month_windows(2023, 2023)
    assert len(windows) == 12
    feb = windows[1]
    assert feb.query_fragment() == "fromdate:1-2-2023 todate:28-2-2023"
    left, right = feb.split()
    assert left.start == feb.start and right.end == feb.end
    assert left.days + right.days == feb.days
    one = Window(date(2023, 1, 1), date(2023, 1, 2))
    a, b = one.split()
    assert a.days == 1 and b.days == 1
