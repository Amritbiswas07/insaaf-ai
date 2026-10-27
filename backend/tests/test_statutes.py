import pytest

from insaaf.domain import LinkedDoc, StatuteRef
from insaaf.processing import statutes as st


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("302", "302"),
        ("120-B", "120B"),
        ("498A", "498A"),
        ("295(A)", "295A"),
        ("394(2)", "394"),
        ("13(1)(d)", "13"),
        (" 438 ", "438"),
        ("13 (1)", "13"),
    ],
)
def test_canonical_section(raw: str, expected: str) -> None:
    assert st.canonical_section(raw) == expected


@pytest.mark.parametrize(
    ("raw", "short"),
    [
        ("IPC", "IPC"),
        ("I.P.C.", "IPC"),
        ("The Indian Penal Code, 1860", "IPC"),
        ("Cr.P.C.", "CrPC"),
        ("Code of Criminal Procedure, 1973", "CrPC"),
        ("BNSS", "BNSS"),
        ("BNS", "BNS"),
        ("Constitution of India", "Constitution"),
        ("N.D.P.S. Act", "NDPS Act"),
        ("Negotiable Instruments Act, 1881", "NI Act"),
        ("Some Obscure Local Act, 1950", "Some Obscure Local Act, 1950"),
    ],
)
def test_canonical_act(raw: str, short: str) -> None:
    assert st.canonical_act(raw)[0] == short


def keys(refs: list[StatuteRef]) -> list[str]:
    return [r.key for r in refs]


def test_extract_section_lists() -> None:
    text = "charged under Sections 302, 307 and 120-B of the Indian Penal Code and u/s. 25 of the Arms Act"
    assert keys(st.extract_from_text(text)) == ["IPC::302", "IPC::307", "IPC::120B", "Arms Act::25"]


def test_extract_abbreviations_and_articles() -> None:
    text = (
        "Bail under Section 439 of Cr.P.C. was sought. Articles 14 and 21 of the Constitution apply. "
        "Section 138 NI Act, and S. 37 of the NDPS Act."
    )
    assert keys(st.extract_from_text(text)) == [
        "CrPC::439",
        "NI Act::138",
        "NDPS Act::37",
        "Constitution::14",
        "Constitution::21",
    ]


def test_ik_title_resolution() -> None:
    ref = st.ref_from_ik_title("Section 302 in The Indian Penal Code", "1560742")
    assert ref is not None and ref.key == "IPC::302" and ref.source_doc_id == "1560742"
    art = st.ref_from_ik_title("Article 21 in Constitution of India")
    assert art is not None and art.label == "Article 21 Constitution"
    assert st.ref_from_ik_title("Ramesh vs State on 1 Jan, 2020") is None


@pytest.mark.parametrize(
    ("anchor", "is_statute"),
    [
        ("302", True),
        ("Sections 302", True),
        ("120-B", True),
        ("295(A)", True),
        ("Article 21", True),
        ("POCSO Act", True),
        ("Sanjay Chandra v. Central Bureau of Investigation", False),
        ("Satender Kumar Antil vs Central Bureau Of Investigation", False),
        ("", False),
    ],
)
def test_anchor_heuristic(anchor: str, is_statute: bool) -> None:
    assert st.looks_like_statute_anchor(anchor) is is_statute


def test_split_links_and_dedupe() -> None:
    links = [LinkedDoc(doc_id="1", anchor_text="302"), LinkedDoc(doc_id="2", anchor_text="Foo vs Bar")]
    statutes, cases = st.split_links(links)
    assert [link.doc_id for link in statutes] == ["1"] and [link.doc_id for link in cases] == ["2"]

    refs = [StatuteRef(act="IPC", section="302"), StatuteRef(act="IPC", section="302", source_doc_id="9"), StatuteRef(act="IPC", section="34")]
    deduped = dict((r.key, (r, n)) for r, n in st.dedupe(refs))
    assert deduped["IPC::302"][1] == 2
    assert deduped["IPC::302"][0].source_doc_id == "9"  # prefers the link-resolved ref
    assert deduped["IPC::34"][1] == 1
