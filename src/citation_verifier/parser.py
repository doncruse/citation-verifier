"""Citation parsing using eyecite with regex fallbacks."""

from __future__ import annotations

import re

from eyecite import get_citations
from eyecite.models import FullCaseCitation

from .models import ParsedCitation
from .state_reporter_map import get_states_for_reporter

_MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# Regex for WestLaw citations: "2018 WL 301424"
_WL_PATTERN = re.compile(r"(\d{4})\s+WL\s+(\d+)")

# Regex for parenthetical court/date: "(S.D.N.Y. Mar. 5, 2018)" or "(S.D.N.Y. 2018)"
_PAREN_PATTERN = re.compile(
    r"\(\s*"
    r"([A-Za-z][A-Za-z.\s]*?)"  # court abbreviation
    r"(?:\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z.]*"  # month
    r"\s+(\d{1,2}),?\s*)?"  # day
    r"\s*(\d{4})"  # year
    r"\s*\)"
)

# Regex for case name: "Plaintiff v. Defendant" before a citation number
# Uses .+? (non-greedy) to stop at the citation number while still matching
# commas, apostrophes, periods in party names like "Macy's Texas, Inc." or "D.A. Adams & Co."
# Matches before ", <digits>" (federal) or " (<year>) <digits>" (California)
_CASE_NAME_PATTERN = re.compile(r"^(.+?)\s+v\.\s+(.+?)(?:,\s+\d|\s+\(\d{4}\)\s+\d)")

# California-style year before reporter: "Case Name (2022) 76 Cal.App.5th 685"
_CAL_YEAR_PATTERN = re.compile(r"\((\d{4})\)\s+\d")

# Trailing year parenthetical to strip from case names: "Inc. (2022)"
_TRAILING_YEAR = re.compile(r"\s*\(\d{4}\)\s*$")

# Docket number: "Case No. 24-cv-9429" or "No. 12-345" — extracted then stripped
_DOCKET_NUMBER_PATTERN = re.compile(r"(?:Case\s+)?No\.\s+(\S+)", re.IGNORECASE)
_DOCKET_JUNK = re.compile(r",?\s*(?:Case\s+)?No\.\s+\S+.*$", re.IGNORECASE)

# Parenthetical with date before court: "(Feb. 5, 2026 SDNY)" or "(Mar. 2020 S.D.N.Y.)"
_PAREN_DATE_COURT_PATTERN = re.compile(
    r"\(\s*"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z.]*"  # month
    r"(?:\s+(\d{1,2}),?)?"  # optional day
    r"\s*(\d{4})"  # year
    r"\s+([A-Za-z][A-Za-z.\s]*?)"  # court abbreviation after year
    r"\s*\)"
)

# Reporter patterns for standard citations
_STANDARD_CITE_PATTERN = re.compile(
    r"(\d+)\s+"
    r"(U\.S\.|S\.\s*Ct\.|L\.\s*Ed(?:\.\s*2d)?|F\.\s*(?:2d|3d|4th)|"
    r"F\.\s*Supp\.?\s*(?:2d|3d)?|F\.\s*App(?:'|')x)"
    r"\s+(\d+)"
)


def _normalize_case_name(case_name: str) -> str:
    """Expand common legal abbreviations in case names for better search matching.

    Based on Indigo Book legal citation guide. Focuses on abbreviations that are
    unambiguous and commonly appear in party names.

    Examples: "Cnty." → "County", "Dept." → "Department", "Inc." → "Incorporated"

    Note: Skips ambiguous single-letter abbreviations (N., S., E., W.) that could
    be initials, and context-dependent terms like "St." (Street vs Saint).
    """
    # Normalize curly/smart apostrophes to straight apostrophes before
    # abbreviation matching so that "Dep\u2019t" matches the same pattern as "Dep't"
    case_name = case_name.replace("\u2018", "'").replace("\u2019", "'")

    # Mapping of abbreviations to full forms (Indigo Book subset)
    # Organized by category for maintainability
    abbrev_map = {
        # Government entities - SAFE
        r"\bCnty\.?\b": "County",
        r"\bCty\.?\b": "County",
        r"\bDep't\b": "Department",
        r"\bDept\.?\b": "Department",
        r"\bComm'n\b": "Commission",
        r"\bComm\.?\b": "Commission",
        r"\bBd\.?\b": "Board",
        r"\bDiv\.?\b": "Division",
        r"\bDist\.?\b": "District",
        r"\bOff\.?\b": "Office",
        r"\bOfc\.?\b": "Office",

        # Organizations - only expand terms CL commonly stores expanded
        # NOTE: Corp., Co., Inc., Ltd., LLC are NOT expanded because
        # CourtListener commonly stores these abbreviated. Expanding them
        # breaks search matching (e.g., "LLC" → "Limited Liability Company"
        # won't match CL's "2715 NMA LLC").
        r"\bAss'n\b": "Association",
        r"\bAssn\.?\b": "Association",

        # Positions - SAFE
        r"\bAdm'r\b": "Administrator",
        r"\bAdmin\.?\b": "Administrator",
        r"\bExec\.?\b": "Executive",
        r"\bDir\.?\b": "Director",
        r"\bSec'y\b": "Secretary",
        r"\bTreas\.?\b": "Treasurer",
        r"\bAtty\.?\b": "Attorney",
        r"\bGen\.?\b": "General",

        # Education - SAFE
        r"\bUniv\.?\b": "University",
        r"\bColl\.?\b": "College",
        r"\bSch\.?\b": "School",
        r"\bEduc\.?\b": "Education",

        # Medical/Health - SAFE
        r"\bHosp\.?\b": "Hospital",
        r"\bMed\.?\b": "Medical",
        r"\bCtr\.?\b": "Center",

        # Business/Services - SAFE
        r"\bIns\.?\b": "Insurance",
        r"\bMfg\.?\b": "Manufacturing",
        r"\bServ\.?\b": "Service",
        r"\bServs\.?\b": "Services",
        r"\bTransp\.?\b": "Transportation",
        r"\bUtil\.?\b": "Utility",
        r"\bPub\.?\b": "Public",

        # Geographic/Organizational scope - SAFE
        r"\bNat'l\b": "National",
        r"\bNatl\.?\b": "National",
        r"\bInt'l\b": "International",
        r"\bIntl\.?\b": "International",

        # Religious - SAFE
        r"\bCath\.?\b": "Catholic",
        r"\bCh\.?\b": "Church",

        # SKIPPED - Ambiguous or risky:
        # - N., S., E., W. (could be initials: "John E. Smith")
        # - St. (Street vs Saint, context-dependent)
        # - Ave., Blvd. (addresses, rarely in case names)
    }

    normalized = case_name
    for abbrev, full_form in abbrev_map.items():
        normalized = re.sub(abbrev, full_form, normalized, flags=re.IGNORECASE)
    return normalized


def _apply_date_fields(
    result: ParsedCitation,
    month_str: str | None,
    day_str: str | None,
    year_str: str | None,
) -> None:
    """Apply parsed date fields to a ParsedCitation object.

    Handles month name lookup, None checks, and int conversion.
    Mutates result in place.
    """
    if month_str and result.month is None:
        result.month = _MONTH_MAP.get(month_str[:3].lower())
    if day_str and result.day is None:
        result.day = int(day_str)
    if year_str and result.year is None:
        result.year = int(year_str)


def parse_citation(text: str) -> ParsedCitation:
    """Parse a citation string into structured components.

    Uses eyecite for standard reporter citations, with regex fallbacks
    for WestLaw citations and parenthetical metadata.
    """
    result = ParsedCitation(raw_text=text)

    # Try eyecite first for standard citations
    eyecite_results = get_citations(text)
    for cite in eyecite_results:
        if isinstance(cite, FullCaseCitation):
            result.volume = str(cite.groups.get("volume", ""))
            result.reporter = str(cite.corrected_reporter() or "")  # type: ignore[no-untyped-call]
            result.page = str(cite.groups.get("page", ""))
            if hasattr(cite, "metadata"):
                meta = cite.metadata
                if hasattr(meta, "court") and meta.court:
                    result.court = meta.court
                if hasattr(meta, "year") and meta.year:
                    try:
                        result.year = int(meta.year)
                    except (ValueError, TypeError):
                        pass
            break  # use first full citation found

    # Check for WestLaw citation
    wl_match = _WL_PATTERN.search(text)
    if wl_match:
        result.is_westlaw = True
        result.wl_number = wl_match.group(2)
        wl_year = int(wl_match.group(1))
        # The WL volume IS the year (e.g. "2025 WL ..." means 2025).
        # Always use it — it's more reliable than a parenthetical year,
        # which may come from a nested "(citing ... (11th Cir. 2006))"
        # parenthetical belonging to a different citation.
        result.year = wl_year

    # California-style year: "(2022) 76 Cal.App.5th 685"
    cal_year_match = _CAL_YEAR_PATTERN.search(text)
    if cal_year_match and result.year is None:
        result.year = int(cal_year_match.group(1))

    # Extract court/date from parenthetical if not already found
    # Try standard format first: "(S.D.N.Y. Sept. 17, 2018)" — court before year
    paren_match = _PAREN_PATTERN.search(text)
    if paren_match:
        if result.court is None:
            result.court = paren_match.group(1).strip()
        _apply_date_fields(
            result, paren_match.group(2), paren_match.group(3), paren_match.group(4)
        )

    # Try reversed format: "(Feb. 5, 2026 SDNY)" — date before court
    if result.court is None:
        date_court_match = _PAREN_DATE_COURT_PATTERN.search(text)
        if date_court_match:
            result.court = date_court_match.group(4).strip()
            _apply_date_fields(
                result,
                date_court_match.group(1),
                date_court_match.group(2),
                date_court_match.group(3),
            )

    # Fallback: extract standard citation components via regex
    if result.volume is None:
        std_match = _STANDARD_CITE_PATTERN.search(text)
        if std_match:
            result.volume = std_match.group(1)
            result.reporter = std_match.group(2)
            result.page = std_match.group(3)

    # Extract case name
    name_match = _CASE_NAME_PATTERN.search(text)
    if name_match:
        result.plaintiff = name_match.group(1).strip()
        result.defendant = name_match.group(2).strip()
        result.case_name = f"{result.plaintiff} v. {result.defendant}"

    # Fallback case name extraction: everything before ", <digits>" or the first
    # reporter citation, whichever comes first
    if result.case_name is None and "v." in text:
        fallback_match = re.match(r"^(.+?\s+v\.\s+.+?),\s+\d", text)
        if fallback_match:
            result.case_name = fallback_match.group(1).strip()
        else:
            # Last resort: split on " v. " and take surrounding text
            parts = text.split(" v. ", 1)
            if len(parts) == 2:
                plaintiff = parts[0].strip()
                # Defendant is everything up to the first number sequence
                defendant = re.split(r",?\s+\d", parts[1])[0].strip()
                if plaintiff and defendant:
                    result.case_name = f"{plaintiff} v. {defendant}"

    # Fallback for "In re" / "Ex parte" / "Matter of" cases (no "v.")
    if result.case_name is None:
        in_re_match = re.match(
            r"^((?:In\s+re|Ex\s+parte|Matter\s+of)\s+.+?),\s+\d",
            text,
            re.IGNORECASE,
        )
        if in_re_match:
            result.case_name = in_re_match.group(1).strip()

    # Extract docket number before cleaning it from the case name
    docket_match = _DOCKET_NUMBER_PATTERN.search(text)
    if docket_match:
        result.docket_number = docket_match.group(1).rstrip(",")

    # Clean trailing year parentheticals from case name: "Inc. (2022)" → "Inc."
    if result.case_name:
        result.case_name = _TRAILING_YEAR.sub("", result.case_name)
        result.case_name = _DOCKET_JUNK.sub("", result.case_name)
        result.case_name = _normalize_case_name(result.case_name)
    if result.defendant:
        result.defendant = _TRAILING_YEAR.sub("", result.defendant)
        result.defendant = _DOCKET_JUNK.sub("", result.defendant)
        result.defendant = _normalize_case_name(result.defendant)
    if result.plaintiff:
        result.plaintiff = _normalize_case_name(result.plaintiff)

    # Infer court from state-specific reporter when no court was parsed
    if result.court is None and result.reporter:
        states = get_states_for_reporter(result.reporter)
        if len(states) == 1:
            result.court = states[0]

    return result


def parsed_citation_from_eyecite(
    cite: FullCaseCitation, raw_text: str = ""
) -> ParsedCitation:
    """Build a ParsedCitation directly from an eyecite FullCaseCitation.

    This avoids the lossy round-trip of serializing to a string and
    re-parsing.  The same post-processing that parse_citation() applies
    (docket-junk stripping, abbreviation normalization, state-court
    inference, etc.) is applied here too.

    Parameters
    ----------
    cite : FullCaseCitation
        An eyecite citation object (typically from ``get_citations()``
        called on full document text).
    raw_text : str
        Display / lookup string stored as ``ParsedCitation.raw_text``.
        Defaults to the empty string.
    """
    result = ParsedCitation(raw_text=raw_text)

    # --- volume / reporter / page from groups ---
    result.volume = str(cite.groups.get("volume", "")) or None
    result.reporter = str(cite.corrected_reporter() or "") or None
    result.page = str(cite.groups.get("page", "")) or None

    # --- metadata fields ---
    meta = cite.metadata
    if hasattr(meta, "court") and meta.court:
        result.court = meta.court
    if hasattr(meta, "plaintiff") and meta.plaintiff:
        result.plaintiff = meta.plaintiff
    if hasattr(meta, "defendant") and meta.defendant:
        result.defendant = meta.defendant

    # Year: prefer the int attribute on the citation object itself
    if cite.year is not None:
        result.year = cite.year
    elif hasattr(meta, "year") and meta.year:
        try:
            result.year = int(meta.year)
        except (ValueError, TypeError):
            pass

    # Month (eyecite stores strings like "Jan.", "Feb.")
    if hasattr(meta, "month") and meta.month:
        result.month = _MONTH_MAP.get(meta.month[:3].lower())

    # Day
    if hasattr(meta, "day") and meta.day:
        try:
            result.day = int(meta.day)
        except (ValueError, TypeError):
            pass

    # --- WestLaw detection ---
    if result.reporter == "WL":
        result.is_westlaw = True
        result.wl_number = result.page
        if result.volume:
            try:
                result.year = int(result.volume)
            except (ValueError, TypeError):
                pass

    # --- Build case_name ---
    if result.plaintiff and result.defendant:
        result.case_name = f"{result.plaintiff} v. {result.defendant}"

    # --- Docket number extraction from raw_text ---
    if raw_text:
        docket_match = _DOCKET_NUMBER_PATTERN.search(raw_text)
        if docket_match:
            result.docket_number = docket_match.group(1).rstrip(",")

    # --- Clean names (same post-processing as parse_citation) ---
    if result.case_name:
        result.case_name = _TRAILING_YEAR.sub("", result.case_name)
        result.case_name = _DOCKET_JUNK.sub("", result.case_name)
        result.case_name = _normalize_case_name(result.case_name)
    if result.defendant:
        result.defendant = _TRAILING_YEAR.sub("", result.defendant)
        result.defendant = _DOCKET_JUNK.sub("", result.defendant)
        result.defendant = _normalize_case_name(result.defendant)
    if result.plaintiff:
        result.plaintiff = _normalize_case_name(result.plaintiff)

    # --- Infer court from state-specific reporter ---
    if result.court is None and result.reporter:
        states = get_states_for_reporter(result.reporter)
        if len(states) == 1:
            result.court = states[0]

    return result
