"""Multi-factor case name similarity matching.

Implements CaseStrainer's 4-factor weighted similarity algorithm:
- 0.25 * sequence_similarity (SequenceMatcher)
- 0.30 * word_overlap (Jaccard index)
- 0.20 * substring_similarity (containment)
- 0.25 * key_word_similarity (filtered meaningful words)

Adapted from: https://github.com/jafrank88/CaseStrainer
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher


class CaseNameMatcher:
    """Multi-factor case name similarity scoring."""

    # Legal abbreviations to expand (normalized from CaseStrainer + our Indigo Book list)
    LEGAL_ABBREVIATIONS = {
        # Corporate
        "inc": "incorporated",
        "corp": "corporation",
        "ltd": "limited",
        "llc": "limited liability company",
        "co": "company",
        "assoc": "association",
        "ass'n": "association",
        "assn": "association",
        "coop": "cooperative",
        "bros": "brothers",
        "comm'r": "commissioner",
        # Titles
        "dr": "doctor",
        "jr": "junior",
        "sr": "senior",
        # Places
        "st": "street",
        "mt": "mount",
        "ft": "fort",
        # Institutions
        "univ": "university",
        "coll": "college",
        "sch": "school",
        "educ": "education",
        "inst": "institute",
        "institutional": "institute",
        "acad": "academic",
        "am": "america",
        "american": "america",
        "labs": "laboratories",
        "lab'ys": "laboratories",
        # Government (from our list + theirs)
        "natl": "national",
        "nat'l": "national",
        "fed": "federal",
        "comm'n": "commission",
        "bd": "board",
        "ctr": "center",
        "dept": "department",
        "dep't": "department",
        "hosp": "hospital",
        "cnty": "county",
        "cty": "county",
        "mfg": "manufacturing",
        "int'l": "international",
        "intl": "international",
        "nw": "northwest",
        "sw": "southwest",
        "dist": "district",
        "munic": "municipal",
        "town": "township",
        "vlg": "village",
        "div": "division",
        "off": "office",
        "ofc": "office",
        "admin": "administrator",
        "adm'r": "administrator",
        "exec": "executive",
        "dir": "director",
        "sec'y": "secretary",
        "secy": "secretary",
        "treas": "treasurer",
        "atty": "attorney",
        "gen": "general",
        "ins": "insurance",
        "info": "information",
        "sol": "solution",
        "sols": "solutions",
        "fin": "finance",
        "serv": "service",
        "servs": "services",
        "transp": "transportation",
        "util": "utility",
        "pub": "public",
        "med": "medical",
        "cath": "catholic",
        "ch": "church",
        # Legal/organizational terms
        "rts": "rights",
        "sys": "system",
        "pol": "political",
        "envtl": "environmental",
        "indus": "industrial",
        "tech": "technology",
        "mgmt": "management",
        "prods": "products",
        "pharm": "pharmaceutical",
        "elec": "electric",
        "telecomms": "telecommunications",
        "just": "justice",
        "petrol": "petroleum",
        "reg'l": "regional",
        "regl": "regional",
        "cmty": "community",
        "hous": "housing",
        # Agency acronyms
        "fbi": "federal bureau of investigation",
        "epa": "environmental protection agency",
        # State abbreviations (Indigo Book)
        # 3+ letter abbreviations are safe from initial collisions.
        # 2-letter ones (ga, la, md, mo, va, vt) omitted — too likely
        # to be personal initials in case names.
        "ala": "alabama",
        "ariz": "arizona",
        "ark": "arkansas",
        "cal": "california",
        "colo": "colorado",
        "conn": "connecticut",
        "del": "delaware",
        "fla": "florida",
        "haw": "hawaii",
        "ida": "idaho",
        "ill": "illinois",
        "ind": "indiana",
        "kan": "kansas",
        "ky": "kentucky",
        "mich": "michigan",
        "minn": "minnesota",
        "miss": "mississippi",
        "mont": "montana",
        "neb": "nebraska",
        "nev": "nevada",
        "okla": "oklahoma",
        "ore": "oregon",
        "tenn": "tennessee",
        "tex": "texas",
        "vt": "vermont",
        "wash": "washington",
        "wis": "wisconsin",
        "wyo": "wyoming",
    }

    # Stop words for key word extraction (from CaseStrainer)
    STOP_WORDS = {
        "the", "of", "and", "in", "on", "at", "to", "for", "with", "by", "from",
        "before", "after", "about", "into", "through", "during", "between", "among",
        "within", "without", "against", "toward", "upon", "until", "since", "while",
        "where", "when", "why", "how", "what", "which", "who", "whom", "whose",
        "this", "that", "these", "those", "a", "an", "as", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "must", "can", "shall", "is", "are", "was", "were", "am",
        "or", "not", "no", "nor", "but", "so", "if", "then", "than", "such", "some",
        "any", "all", "both", "each", "few", "more", "most", "other", "another",
        "much", "many", "one", "two", "three", "first", "second", "last", "next",
        "only", "own", "same", "very", "just", "also", "even", "well", "back",
    }

    def __init__(self):
        pass

    def calculate_similarity(self, name1: str, name2: str) -> float:
        """Calculate multi-factor similarity score between two case names.

        Args:
            name1: First case name (may be abbreviated, e.g. "Fink v. Gomez")
            name2: Second case name (may be full, e.g. "David M. Fink v. James H. Gomez, Director...")

        Returns:
            Similarity score from 0.0 to 1.0
        """
        if not name1 or not name2:
            return 0.0

        # Normalize both names
        norm1 = self._normalize(name1)
        norm2 = self._normalize(name2)

        if not norm1 or not norm2:
            return 0.0

        # Component 1: Sequence similarity (0.25 weight)
        seq_similarity = SequenceMatcher(None, norm1, norm2).ratio()

        # Component 2: Word overlap similarity (0.30 weight)
        words1 = set(norm1.split())
        words2 = set(norm2.split())
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        word_similarity = intersection / union if union > 0 else 0.0

        # Component 3: Substring similarity (0.20 weight)
        substring_similarity = 0.0
        if norm1 in norm2 or norm2 in norm1:
            substring_similarity = min(len(norm1), len(norm2)) / max(len(norm1), len(norm2))

        # Component 4: Key word similarity (0.25 weight)
        key_words1 = self._extract_key_words(norm1)
        key_words2 = self._extract_key_words(norm2)
        if key_words1 and key_words2:
            key_intersection = len(key_words1.intersection(key_words2))
            key_union = len(key_words1.union(key_words2))
            key_word_similarity = key_intersection / key_union if key_union > 0 else 0.0
        else:
            key_word_similarity = 0.0

        # Weighted combination
        combined_similarity = (
            0.25 * seq_similarity +
            0.30 * word_similarity +
            0.20 * substring_similarity +
            0.25 * key_word_similarity
        )

        # Abbreviated name boost: If one name is short (≤4 words) and all its words
        # appear in the other name, it's likely an abbreviated citation.
        # Example: "Fink v. Gomez" vs "David M. Fink v. James H. Gomez, Director..."
        #
        # EXCEPTION: Skip boost for "In re" cases. "In re [Surname]" is so generic
        # that subset matching produces false positives (e.g., "In re Wright" matches
        # "In re Wright, Minors" or "In re Ramirez" matches "In re Faith Ramirez v.
        # The State of Texas"). The 4-factor score alone is sufficient for these.
        is_in_re = "in re" in norm1 or "in re" in norm2
        if not is_in_re:
            if len(words1) <= 4 and words1.issubset(words2):
                combined_similarity = max(combined_similarity, 0.85)
            elif len(words2) <= 4 and words2.issubset(words1):
                combined_similarity = max(combined_similarity, 0.85)

        return round(combined_similarity, 4)

    def _normalize(self, case_name: str) -> str:
        """Normalize a case name for comparison.

        Pipeline:
        1. Lower case & strip
        2. Collapse whitespace
        3. Normalize legal prefixes (State, Commonwealth, In re, etc.)
        4. Expand abbreviations
        5. Drop corporate suffixes and party roles
        6. Remove non-word characters
        """
        normalized = case_name.lower().strip()

        # Normalize curly/smart apostrophes to straight apostrophes
        # so "dep\u2019t" matches the same abbreviation pattern as "dep't"
        normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")

        # Collapse whitespace
        normalized = re.sub(r"\s+", " ", normalized)

        # Normalize legal prefixes
        # Map "in the matter of", "matter of", "re" → "in re"
        normalized = re.sub(r"\bin the matter of\b", "in re", normalized)
        normalized = re.sub(r"\bmatter of\b", "in re", normalized)
        normalized = re.sub(r"\bex rel\.?\b", "in re", normalized)

        # Map "commonwealth", "people" → "state"
        normalized = re.sub(r"\bcommonwealth\b", "state", normalized)
        normalized = re.sub(r"\bpeople\b", "state", normalized)

        # Map "u.s.", "us", "federal" → "united states"
        normalized = re.sub(r"\bu\.?s\.?\b", "united states", normalized)
        normalized = re.sub(r"\bfederal\b", "united states", normalized)

        # Normalize "&" to "and" before abbreviation expansion and
        # non-word character removal (which would strip "&" entirely)
        normalized = re.sub(r"\s*&\s*", " and ", normalized)

        # Expand abbreviations
        for abbrev, expansion in self.LEGAL_ABBREVIATIONS.items():
            pattern = r"\b" + re.escape(abbrev) + r"\b"
            normalized = re.sub(pattern, expansion, normalized)

        # Drop corporate suffixes
        suffixes_to_remove = [
            r",\s*incorporated",
            r",\s*corporation",
            r",\s*limited",
            r",\s*limited liability company",
            r",\s*company",
        ]
        for suffix in suffixes_to_remove:
            normalized = re.sub(suffix, "", normalized)

        # Drop party roles
        party_roles = [
            r",\s*petitioner",
            r",\s*respondent",
            r",\s*appellant",
            r",\s*appellee",
            r",\s*defendant",
            r",\s*plaintiff",
            r",\s*relator",
        ]
        for role in party_roles:
            normalized = re.sub(role, "", normalized)

        # Collapse period-separated initials into single tokens:
        # "l.p." → "lp", "n.e." → "ne", "u.s.a." → "usa"
        # This must happen before removing non-word characters, which
        # would turn "l.p." into "l p" (two separate tokens).
        normalized = re.sub(
            r"\b([a-z])\.([a-z])\.?(?=\s|$)",
            r"\1\2",
            normalized,
        )

        # Remove non-word characters (keep spaces)
        normalized = re.sub(r"[^\w\s]", " ", normalized)

        # Final whitespace collapse
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return normalized

    def _extract_key_words(self, normalized_text: str) -> set[str]:
        """Extract meaningful keywords by filtering out stop words.

        Args:
            normalized_text: Normalized case name text

        Returns:
            Set of filtered keywords (>2 chars, not stop words)
        """
        words = normalized_text.split()
        key_words = {
            word for word in words
            if len(word) > 2 and word not in self.STOP_WORDS
        }
        return key_words
