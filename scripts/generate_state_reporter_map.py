#!/usr/bin/env python3
"""Generate comprehensive state reporter mapping from courts-db.

This script builds a mapping from state reporter abbreviations to court IDs
using Free Law Project's courts-db package.
"""

from courts_db import courts

# State abbreviations used in reporters
STATE_ABBREVS = {
    "Ala.": "ala",
    "Alaska": "alaska",
    "Ariz.": "ariz",
    "Ark.": "ark",
    "Cal.": "cal",
    "Colo.": "colo",
    "Conn.": "conn",
    "Del.": "del",
    "Fla.": "fla",
    "Ga.": "ga",
    "Haw.": "haw",
    "Idaho": "idaho",
    "Ill.": "ill",
    "Ind.": "ind",
    "Iowa": "iowa",
    "Kan.": "kan",
    "Ky.": "ky",
    "La.": "la",
    "Me.": "me",
    "Md.": "md",
    "Mass.": "mass",
    "Mich.": "mich",
    "Minn.": "minn",
    "Miss.": "miss",
    "Mo.": "mo",
    "Mont.": "mont",
    "Neb.": "neb",
    "Nev.": "nev",
    "N.H.": "nh",
    "N.J.": "nj",
    "N.M.": "nm",
    "N.Y.": "ny",
    "N.C.": "nc",
    "N.D.": "nd",
    "Ohio": "ohio",
    "Okla.": "okla",
    "Or.": "or",
    "Pa.": "pa",
    "R.I.": "ri",
    "S.C.": "sc",
    "S.D.": "sd",
    "Tenn.": "tenn",
    "Tex.": "tex",
    "Utah": "utah",
    "Vt.": "vt",
    "Va.": "va",
    "Wash.": "wash",
    "W.Va.": "wva",
    "Wis.": "wis",
    "Wyo.": "wyo",
}


def find_court(state_id: str, court_type: str = "appellate") -> str | None:
    """Find the primary court of a given type for a state.

    Args:
        state_id: State identifier (e.g., "kan", "cal")
        court_type: "appellate" for supreme/appellate, "trial" for trial

    Returns:
        Court ID or None if not found
    """
    # Find all courts for this state
    state_courts = [
        c for c in courts
        if c["id"].startswith(state_id)
        and c["system"] == "state"
        and c.get("type") == court_type
    ]

    if not state_courts:
        return None

    # For appellate courts, prefer supreme court
    if court_type == "appellate":
        supreme = [c for c in state_courts if "supreme" in c["name"].lower()]
        if supreme:
            return supreme[0]["id"]
        # Fall back to first appellate court
        return state_courts[0]["id"]

    return state_courts[0]["id"]


def find_appellate_court(state_id: str) -> str | None:
    """Find the general appellate court (not supreme) for a state."""
    state_courts = [
        c for c in courts
        if c["id"].startswith(state_id)
        and c["system"] == "state"
        and c.get("type") == "appellate"
        and "supreme" not in c["name"].lower()
        and "attorney general" not in c["name"].lower()
    ]

    if not state_courts:
        return None

    # Prefer courts with "appeal" in the name but not "district"
    appeals = [c for c in state_courts if "appeal" in c["name"].lower()]
    if appeals:
        return appeals[0]["id"]

    return state_courts[0]["id"]


def generate_mapping():
    """Generate the complete state reporter mapping."""
    mapping = {}

    for state_abbrev, state_id in sorted(STATE_ABBREVS.items()):
        # Find supreme court for this state
        supreme_ct = find_court(state_id, "appellate")
        if not supreme_ct:
            print(f"WARNING: No supreme court found for {state_abbrev} ({state_id})")
            continue

        # Map basic reporter: "Kan." -> ["kan"]
        mapping[state_abbrev] = [supreme_ct]

        # Map series: "Kan. 2d", "Kan. 3d", etc.
        for series in ["2d", "3d", "4th", "5th"]:
            mapping[f"{state_abbrev} {series}"] = [supreme_ct]

        # Map appellate reporter if different from supreme
        appellate_ct = find_appellate_court(state_id)
        if appellate_ct and appellate_ct != supreme_ct:
            # "Cal. App." -> ["calctapp"]
            mapping[f"{state_abbrev} App."] = [appellate_ct]
            for series in ["2d", "3d", "4th", "5th"]:
                mapping[f"{state_abbrev} App. {series}"] = [appellate_ct]

    return mapping


if __name__ == "__main__":
    mapping = generate_mapping()

    print("# Generated state reporter mapping")
    print(f"# Total reporters mapped: {len(mapping)}\n")

    for reporter, court_ids in sorted(mapping.items()):
        print(f'    "{reporter}": {court_ids},')
