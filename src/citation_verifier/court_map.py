"""Mapping of court abbreviations to CourtListener court IDs."""

from __future__ import annotations

import re

# Federal district courts
COURT_MAP: dict[str, str] = {
    # Supreme Court
    "U.S.": "scotus",
    "SCOTUS": "scotus",
    # Circuit Courts
    "1st Cir.": "ca1",
    "2d Cir.": "ca2",
    "2nd Cir.": "ca2",
    "3d Cir.": "ca3",
    "3rd Cir.": "ca3",
    "4th Cir.": "ca4",
    "5th Cir.": "ca5",
    "6th Cir.": "ca6",
    "7th Cir.": "ca7",
    "8th Cir.": "ca8",
    "9th Cir.": "ca9",
    "10th Cir.": "ca10",
    "11th Cir.": "ca11",
    "D.C. Cir.": "cadc",
    "Fed. Cir.": "cafc",
    # District courts — 1st Circuit
    "D. Me.": "med",
    "D. Mass.": "mad",
    "D.N.H.": "nhd",
    "D.R.I.": "rid",
    "D.P.R.": "prd",
    # District courts — 2nd Circuit
    "N.D.N.Y.": "nynd",
    "S.D.N.Y.": "nysd",
    "E.D.N.Y.": "nyed",
    "W.D.N.Y.": "nywd",
    "D. Conn.": "ctd",
    "D. Vt.": "vtd",
    # District courts — 3rd Circuit
    "D.N.J.": "njd",
    "E.D. Pa.": "paed",
    "M.D. Pa.": "pamd",
    "W.D. Pa.": "pawd",
    "D. Del.": "ded",
    "D.V.I.": "vid",
    # District courts — 4th Circuit
    "D. Md.": "mdd",
    "E.D.N.C.": "nced",
    "M.D.N.C.": "ncmd",
    "W.D.N.C.": "ncwd",
    "D.S.C.": "scd",
    "E.D. Va.": "vaed",
    "W.D. Va.": "vawd",
    "N.D.W. Va.": "wvnd",
    "N.D. W. Va.": "wvnd",
    "S.D.W. Va.": "wvsd",
    "S.D. W. Va.": "wvsd",
    # District courts — 5th Circuit
    "E.D. La.": "laed",
    "M.D. La.": "lamd",
    "W.D. La.": "lawd",
    "N.D. Miss.": "msnd",
    "S.D. Miss.": "mssd",
    "E.D. Tex.": "txed",
    "N.D. Tex.": "txnd",
    "S.D. Tex.": "txsd",
    "W.D. Tex.": "txwd",
    # District courts — 6th Circuit
    "E.D. Ky.": "kyed",
    "W.D. Ky.": "kywd",
    "E.D. Mich.": "mied",
    "W.D. Mich.": "miwd",
    "N.D. Ohio": "ohnd",
    "S.D. Ohio": "ohsd",
    "E.D. Tenn.": "tned",
    "M.D. Tenn.": "tnmd",
    "W.D. Tenn.": "tnwd",
    # District courts — 7th Circuit
    "C.D. Ill.": "ilcd",
    "N.D. Ill.": "ilnd",
    "S.D. Ill.": "ilsd",
    "N.D. Ind.": "innd",
    "S.D. Ind.": "insd",
    "E.D. Wis.": "wied",
    "W.D. Wis.": "wiwd",
    # District courts — 8th Circuit
    "E.D. Ark.": "ared",
    "W.D. Ark.": "arwd",
    "D. Iowa": "iad",  # only one district - no split
    "N.D. Iowa": "iand",
    "S.D. Iowa": "iasd",
    "D. Minn.": "mnd",
    "E.D. Mo.": "moed",
    "W.D. Mo.": "mowd",
    "D. Neb.": "ned",
    "D.N.D.": "ndd",
    "D.S.D.": "sdd",
    # District courts — 9th Circuit
    "D. Alaska": "akd",
    "D. Ariz.": "azd",
    "C.D. Cal.": "cacd",
    "E.D. Cal.": "caed",
    "N.D. Cal.": "cand",
    "S.D. Cal.": "casd",
    "D. Guam": "gud",
    "D. Haw.": "hid",
    "D. Idaho": "idd",
    "D. Mont.": "mtd",
    "D. Nev.": "nvd",
    "D. Or.": "ord",
    "E.D. Wash.": "waed",
    "W.D. Wash.": "wawd",
    "D.N. Mar. I.": "nmid",
    # District courts — 10th Circuit
    "D. Colo.": "cod",
    "D. Kan.": "ksd",
    "D.N.M.": "nmd",
    "E.D. Okla.": "oked",
    "N.D. Okla.": "oknd",
    "W.D. Okla.": "okwd",
    "D. Utah": "utd",
    "D. Wyo.": "wyd",
    # District courts — 11th Circuit
    "M.D. Ala.": "almd",
    "N.D. Ala.": "alnd",
    "S.D. Ala.": "alsd",
    "M.D. Fla.": "flmd",
    "N.D. Fla.": "flnd",
    "S.D. Fla.": "flsd",
    "M.D. Ga.": "gamd",
    "N.D. Ga.": "gand",
    "S.D. Ga.": "gasd",
    # DC
    "D.D.C.": "dcd",
}

# Build a normalized lookup: strip dots and spaces, lowercase
# Build reverse lookup: CL ID → canonical abbreviation (first one wins)
_NORMALIZED: dict[str, str] = {}
_KNOWN_IDS: set[str] = set()
_ID_TO_ABBREV: dict[str, str] = {}
for abbr, cl_id in COURT_MAP.items():
    normalized = re.sub(r"[\s.]", "", abbr).lower()
    _NORMALIZED[normalized] = cl_id
    _KNOWN_IDS.add(cl_id)
    if cl_id not in _ID_TO_ABBREV:
        _ID_TO_ABBREV[cl_id] = abbr


def is_federal_court(court_id: str) -> bool:
    """Return True if the court ID is a known federal court.

    COURT_MAP only covers federal courts, so any ID in _KNOWN_IDS is federal.
    Bankruptcy court IDs (ending in 'b') are also federal if their corresponding
    district court ID (ending in 'd') is known.
    Used to skip RECAP searches for state courts (RECAP is PACER data only).
    """
    if court_id in _KNOWN_IDS:
        return True
    # Bankruptcy courts: 'nysb' → check if 'nysd' is known
    if court_id.endswith("b"):
        return (court_id[:-1] + "d") in _KNOWN_IDS
    return False


def lookup_court_abbrev(court_id: str) -> str | None:
    """Look up the canonical abbreviation for a CourtListener court ID.

    Returns the standard legal abbreviation (e.g. "7th Cir.", "S.D. Fla.")
    or None if the ID is not a known federal court.
    """
    return _ID_TO_ABBREV.get(court_id)


def lookup_court_id(court_str: str) -> str | None:
    """Look up a CourtListener court ID from a court abbreviation.

    Handles variations like "S.D.N.Y.", "SDNY", "S.D. N.Y." etc.
    Also accepts CL court IDs directly (e.g. "almd", "nysd").
    Handles "Bankr." prefix: "Bankr. S.D.N.Y." → "nysb".
    """
    if not court_str:
        return None

    # If it's already a known CL court ID, return it directly
    if court_str in _KNOWN_IDS:
        return court_str

    # Handle "Bankr." prefix — strip it, look up the district court,
    # then convert district ID to bankruptcy ID (trailing 'd' → 'b').
    bankr_match = re.match(r"Bankr\.?\s+(.+)", court_str, re.IGNORECASE)
    if bankr_match:
        district_str = bankr_match.group(1)
        district_id = lookup_court_id(district_str)
        if district_id and district_id.endswith("d"):
            return district_id[:-1] + "b"
        return None

    # Try exact match first
    if court_str in COURT_MAP:
        return COURT_MAP[court_str]

    # Try normalized match
    normalized = re.sub(r"[\s.]", "", court_str).lower()
    return _NORMALIZED.get(normalized)
