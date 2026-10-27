"""Statute reference extraction and canonicalisation.

The old pipeline let the LLM invent node ids ("Section 302 IPC", "S. 302 of
IPC", "Sec 302 Indian Penal Code" became three different nodes). Here every
reference is normalised to a stable key such as ``IPC::302`` so the graph can
answer "which cases apply Section 302 IPC?" reliably.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from insaaf.domain import LinkedDoc, StatuteRef

# canonical short name -> (full name, regex alternatives as they appear in judgments)
ACTS: dict[str, tuple[str, list[str]]] = {
    "IPC": ("Indian Penal Code, 1860", [r"I\.?\s?P\.?\s?C\.?", r"Indian Penal Code", r"Penal Code"]),
    "CrPC": (
        "Code of Criminal Procedure, 1973",
        [r"Cr\.?\s?P\.?\s?C\.?", r"Code of Criminal Procedure", r"Criminal Procedure Code"],
    ),
    "CPC": ("Code of Civil Procedure, 1908", [r"C\.?\s?P\.?\s?C\.?", r"Code of Civil Procedure", r"Civil Procedure Code"]),
    "BNS": ("Bharatiya Nyaya Sanhita, 2023", [r"B\.?\s?N\.?\s?S\.?(?!\.?\s?S)", r"Bharatiya Nyaya Sanhita"]),
    "BNSS": ("Bharatiya Nagarik Suraksha Sanhita, 2023", [r"B\.?\s?N\.?\s?S\.?\s?S\.?", r"Bharatiya Nagarik Suraksha Sanhita"]),
    "BSA": ("Bharatiya Sakshya Adhiniyam, 2023", [r"Bharatiya Sakshya Adhiniyam"]),
    "Evidence Act": ("Indian Evidence Act, 1872", [r"(?:Indian\s+)?Evidence Act"]),
    "Constitution": ("Constitution of India", [r"Constitution(?: of India)?"]),
    "NDPS Act": (
        "Narcotic Drugs and Psychotropic Substances Act, 1985",
        [r"N\.?D\.?P\.?S\.?(?: Act)?", r"Narcotic Drugs and Psychotropic Substances Act"],
    ),
    "POCSO Act": (
        "Protection of Children from Sexual Offences Act, 2012",
        [r"POCSO(?: Act)?", r"Protection of Children from Sexual Offences Act"],
    ),
    "NI Act": ("Negotiable Instruments Act, 1881", [r"N\.?\s?I\.? Act", r"Negotiable Instruments Act"]),
    "MCOCA": ("Maharashtra Control of Organised Crime Act, 1999", [r"MCOCA", r"Maharashtra Control of Organised Crime Act"]),
    "PC Act": ("Prevention of Corruption Act, 1988", [r"P\.?\s?C\.? Act", r"Prevention of Corruption Act"]),
    "UAPA": ("Unlawful Activities (Prevention) Act, 1967", [r"UAPA", r"Unlawful Activities \(Prevention\) Act"]),
    "Arbitration Act": ("Arbitration and Conciliation Act, 1996", [r"Arbitration and Conciliation Act", r"Arbitration Act"]),
    "IBC": ("Insolvency and Bankruptcy Code, 2016", [r"IBC", r"Insolvency and Bankruptcy Code"]),
    "Specific Relief Act": ("Specific Relief Act, 1963", [r"Specific Relief Act"]),
    "TPA": ("Transfer of Property Act, 1882", [r"T\.?\s?P\.? Act", r"Transfer of Property Act"]),
    "Limitation Act": ("Limitation Act, 1963", [r"Limitation Act"]),
    "Companies Act": ("Companies Act, 2013", [r"Companies Act"]),
    "Income Tax Act": ("Income Tax Act, 1961", [r"Income[- ]Tax Act", r"I\.?\s?T\.? Act(?!,? 2000)"]),
    "IT Act 2000": ("Information Technology Act, 2000", [r"Information Technology Act"]),
    "Hindu Marriage Act": ("Hindu Marriage Act, 1955", [r"Hindu Marriage Act"]),
    "DV Act": (
        "Protection of Women from Domestic Violence Act, 2005",
        [r"D\.?\s?V\.? Act", r"Protection of Women from Domestic Violence Act", r"Domestic Violence Act"],
    ),
    "MV Act": ("Motor Vehicles Act, 1988", [r"M\.?\s?V\.? Act", r"Motor Vehicles Act"]),
    "JJ Act": ("Juvenile Justice (Care and Protection of Children) Act", [r"J\.?\s?J\.? Act", r"Juvenile Justice[^,.;]{0,40}Act"]),
    "ID Act": ("Industrial Disputes Act, 1947", [r"I\.?\s?D\.? Act", r"Industrial Disputes Act"]),
    "Copyright Act": ("Copyright Act, 1957", [r"Copyright Act"]),
    "Trade Marks Act": ("Trade Marks Act, 1999", [r"Trade ?Marks Act"]),
    "Arms Act": ("Arms Act, 1959", [r"Arms Act"]),
    "SC/ST Act": (
        "Scheduled Castes and Scheduled Tribes (Prevention of Atrocities) Act, 1989",
        [r"SC/ST(?:\s*\(PoA\))? Act", r"Atrocities Act", r"Scheduled Castes and (?:the )?Scheduled Tribes \(Prevention of Atrocities\) Act"],
    ),
    "MRTP Act": ("Maharashtra Regional and Town Planning Act, 1966", [r"MRTP Act", r"Maharashtra Regional and Town Planning Act"]),
}

_ACT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (short, re.compile(rf"^(?:the\s+)?(?:{'|'.join(alts)})(?:,?\s*\d{{4}})?\.?$", re.I))
    for short, (_, alts) in ACTS.items()
]
_ACT_ALT = "|".join(f"(?:{a})" for _, (_, alts) in ACTS.items() for a in alts)

_SEC = r"\d{1,4}[A-Z]{0,2}(?:-[A-Z])?(?:\s?\(\s?[0-9a-zA-Z]{1,4}\s?\))*"
_SEC_LIST = rf"(?P<secs>{_SEC}(?:\s*(?:,|&|/|and|r/w|read with)\s*{_SEC})*)"

SECTION_RE = re.compile(
    rf"\b(?:Sections?|Secs?\.?|S\.|u/s\.?|U/s\.?)\s*{_SEC_LIST}\s*(?:of\s+)?(?:the\s+)?(?P<act>{_ACT_ALT})",
    re.I,
)
ARTICLE_RE = re.compile(
    rf"\bArt(?:icles?|s?\.)\s*{_SEC_LIST}\s*of\s+(?:the\s+)?Constitution", re.I
)
_SPLIT_SECS = re.compile(r"\s*(?:,|&|/|\band\b|r/w|read with)\s*", re.I)

# Indian Kanoon statute doc titles: "Section 302 in The Indian Penal Code",
# "Article 21 in Constitution of India", "Section 3 in The Arms Act, 1959"
_IK_TITLE = re.compile(r"^(?P<kind>Section|Article|Rule|Order)\s+(?P<num>[\w\-()]+)\s+in\s+(?P<act>.+)$", re.I)
_STATUTE_ANCHOR = re.compile(
    r"^(?:(?:Sections?|Secs?\.?|S\.|Articles?|Art\.|Rule|Order|u/s\.?)\s*)?[\dA-Z]{1,5}(?:[-\s]?[A-Z])?(?:\s?\(\w{1,4}\))*\.?$",
    re.I,
)


def canonical_section(raw: str) -> str:
    """'120-B' -> '120B', '295(A)' -> '295A', '394(2)' -> '394', ' 302 ' -> '302'."""
    s = raw.strip().replace(" ", "")
    # An upper-case letter in brackets is part of the section number (295(A) == 295A);
    # digits / lower-case letters are sub-sections and clauses, which we drop.
    s = re.sub(r"^(\d+)\(([A-Z]{1,2})\)", r"\1\2", s).upper()
    s = re.sub(r"\(.*$", "", s)
    s = s.replace("-", "")
    m = re.match(r"\d+[A-Z]{0,2}", s)
    return m.group(0) if m else s


def canonical_act(name: str) -> tuple[str, str]:
    """Map any spelling of an Act to (short_name, full_name)."""
    cleaned = re.sub(r"\s+", " ", name).strip(" .,")
    for short, pattern in _ACT_PATTERNS:
        if pattern.match(cleaned):
            return short, ACTS[short][0]
    # Unknown act: keep a tidy version of its own name.
    tidy = re.sub(r"^the\s+", "", cleaned, flags=re.I)
    return tidy, tidy


def extract_from_text(text: str) -> list[StatuteRef]:
    refs: list[StatuteRef] = []
    for m in SECTION_RE.finditer(text):
        act, full = canonical_act(m.group("act"))
        for sec in _SPLIT_SECS.split(m.group("secs")):
            if sec.strip():
                refs.append(StatuteRef(act=act, section=canonical_section(sec), act_full_name=full))
    for m in ARTICLE_RE.finditer(text):
        for art in _SPLIT_SECS.split(m.group("secs")):
            if art.strip():
                refs.append(
                    StatuteRef(act="Constitution", section=canonical_section(art), act_full_name=ACTS["Constitution"][0])
                )
    return refs


def ref_from_ik_title(title: str, doc_id: str | None = None) -> StatuteRef | None:
    """Resolve an Indian Kanoon statute document title to a StatuteRef."""
    if m := _IK_TITLE.match(title.strip()):
        act, full = canonical_act(m.group("act"))
        return StatuteRef(act=act, section=canonical_section(m.group("num")), act_full_name=full, source_doc_id=doc_id)
    return None


def looks_like_statute_anchor(anchor: str) -> bool:
    """Heuristic: link text such as 'Section 302', '120-B', 'Article 21'
    points at a statute; long party-name text points at a judgment."""
    a = anchor.strip()
    if not a:
        return False
    if _STATUTE_ANCHOR.match(a):
        return True
    return bool(
        len(a) <= 80
        and re.search(r"\b(Act|Code|Sanhita|Constitution|Rules|Regulations?)\b", a)
        and " vs" not in a.lower()
    )


def split_links(links: Iterable[LinkedDoc]) -> tuple[list[LinkedDoc], list[LinkedDoc]]:
    """Partition linked docs into (probable statutes, probable case citations)."""
    statutes, cases = [], []
    for link in links:
        (statutes if looks_like_statute_anchor(link.anchor_text) else cases).append(link)
    return statutes, cases


def dedupe(refs: Iterable[StatuteRef]) -> list[tuple[StatuteRef, int]]:
    """Collapse duplicates, keeping a mention count per canonical key."""
    seen: dict[str, tuple[StatuteRef, int]] = {}
    for r in refs:
        if r.key in seen:
            prev, n = seen[r.key]
            seen[r.key] = (prev if prev.source_doc_id else r, n + 1)
        else:
            seen[r.key] = (r, 1)
    return list(seen.values())
