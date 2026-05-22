"""Phase 3 Task 5 unit tests for caption_investigation.

All tests mock client.get_cluster / get_docket / get_opinion_text.
The corpus-level acceptance happens in test_phase3_corpus_acceptance.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from citation_verifier.models import StageName, StageVerdict, Status, WarningCategory
from citation_verifier.verifier import CitationVerifier


def _client_with_mismatch(
    cited_case_name_in_lookup: str,
    cluster_id: int,
    case_name_full: str = "",
    docket_id: int | None = None,
    docket_case_name: str = "",
    opinion_text: str = "",
):
    """Build a mock client that returns a citation_lookup hit with a
    name mismatch + populated caption_investigation responses."""
    client = MagicMock()
    client.citation_lookup.return_value = [
        {
            "clusters": [
                {
                    "case_name": cited_case_name_in_lookup,
                    "id": cluster_id,
                    "absolute_url": f"/opinion/{cluster_id}/",
                    "citations": [
                        {"volume": "857", "reporter": "F.3d", "page": "267"},
                    ],
                }
            ]
        }
    ]
    client.search_opinions.return_value = []
    client.search_recap.return_value = []
    client.get_docket_entries.return_value = []
    client.get_cluster.return_value = {
        "id": cluster_id,
        "case_name_full": case_name_full,
        "docket_id": docket_id,
    }
    client.get_docket.return_value = (
        {"case_name": docket_case_name} if docket_id else {}
    )
    client.get_opinion_text.return_value = opinion_text or None
    return client


class TestCaptionInvestigationOpensStage:
    def test_path_includes_caption_investigation_entry_on_mismatch(self):
        """When citation_lookup hits a mismatched caption, the resolution_path
        must include a caption_investigation stage entry.

        Setup: brief says "Morrison v. Green", CL cluster shows "Thompson v. Brown"
        (no overlap on any party), so investigation fires and the docket is checked.
        The docket has "Morrison v. Green" which passes party-overlap.
        """
        client = _client_with_mismatch(
            "Thompson v. Brown",       # CL abbreviated/stale cluster name
            cluster_id=4390987,
            case_name_full="Thompson v. Brown",
            docket_id=12345,
            docket_case_name="Morrison v. Green",  # docket has the real name
        )
        v = CitationVerifier(client)
        result = v.verify("Morrison v. Green, 857 F.3d 267 (5th Cir. 2017)")

        stages = [e.stage for e in result.resolution_path]
        assert StageName.citation_lookup in stages
        assert StageName.caption_investigation in stages


class TestCaptionInvestigationOutcomes:
    def test_party_overlap_in_docket_caption_yields_verified_data_bug(self):
        """CL cluster has a stale/different caption, but docket has the real
        full caption that matches the brief → VERIFIED + cl_display_name_data_bug.

        This is the Koch-shaped scenario: the brief's plaintiff surname is absent
        from the cluster's case_name but present in the docket's case_name.
        """
        client = _client_with_mismatch(
            "Thompson v. Brown",       # CL abbreviated/stale cluster name
            cluster_id=4390987,
            case_name_full="Thompson v. Brown",
            docket_id=12345,
            docket_case_name="Morrison v. Green",  # docket has the real name
        )
        v = CitationVerifier(client)
        result = v.verify("Morrison v. Green, 857 F.3d 267 (5th Cir. 2017)")
        assert result.status == Status.VERIFIED
        cats = {w.category for w in result.warnings}
        assert WarningCategory.cl_display_name_data_bug in cats

    def test_no_party_overlap_yields_wrong_case(self):
        """Hogan named exemplar shape: cluster resolves but parties
        completely differ from the brief — escalate to WRONG_CASE.

        'Hogan v. AT&T' vs 'U.S. ex rel. Green v. Washington': none of
        'hogan', 'att' appear in Green/Washington → WRONG_CASE.
        Per design §2.4: final_ids still populate with the actual CL cluster.
        """
        client = _client_with_mismatch(
            "U.S. ex rel. Green v. Washington",
            cluster_id=2140439,
            case_name_full="United States ex rel. Green v. Washington",
            docket_id=999,
            docket_case_name="United States ex rel. Green v. Washington",
            opinion_text=(
                "UNITED STATES OF AMERICA EX REL. RICHARD GREEN, "
                "Plaintiff, v. WASHINGTON, et al. Defendants. "
                "Memorandum Opinion ..."
            ),
        )
        v = CitationVerifier(client)
        result = v.verify("Hogan v. AT&T, Inc., 917 F. Supp. 1275 (S.D. Tex. 1994)")
        assert result.status == Status.WRONG_CASE
        # IDs still populate per design §2.4: "expected_final_ids point
        # to the actual case the reporter resolves to, not the brief's
        # fake name."
        assert result.final_ids.cluster_id == 2140439

    def test_formatting_noise_yields_verified(self):
        """Cosmetic divergence on Inc./Incorporated, punctuation, etc.
        Per the caption-investigator decision: this is either name_formatting_noise
        or cl_display_name_data_bug, but status is VERIFIED.

        NOTE: depending on how _names_match_citation_lookup handles the
        Corp./Corporation difference, the mismatch may not flag at all
        (if the name-lookup check passes, caption_investigation is skipped
        and the result is just VERIFIED with no warning). Either way the
        test asserts VERIFIED — the load-bearing corpus assertion is in Task 6.
        """
        client = MagicMock()
        client.citation_lookup.return_value = [
            {
                "clusters": [
                    {
                        "case_name": "Acme Corporation v. Smith",  # CL has "Corporation"
                        "id": 111,
                        "absolute_url": "/opinion/111/",
                        # Cluster includes the primary reporter citation so
                        # VERIFIED_PARTIAL does not fire (primary IS present).
                        "citations": [
                            {"volume": "100", "reporter": "F.3d", "page": "200"},
                        ],
                    }
                ]
            }
        ]
        client.search_opinions.return_value = []
        client.search_recap.return_value = []
        client.get_docket_entries.return_value = []
        client.get_cluster.return_value = {
            "id": 111,
            "case_name_full": "Acme Corporation v. Smith",
            "docket_id": 222,
        }
        client.get_docket.return_value = {"case_name": "Acme Corporation v. Smith"}
        client.get_opinion_text.return_value = None

        v = CitationVerifier(client)
        # "Acme Corp. v. Smith" — Corp. abbreviates Corporation.
        result = v.verify("Acme Corp. v. Smith, 100 F.3d 200 (2d Cir. 2020)")
        # Whether or not caption_investigation fires, the result should be VERIFIED
        # because "Acme Corp." vs "Acme Corporation" is either a pass through
        # _names_match_citation_lookup (no mismatch → no investigation needed)
        # or classified as name_formatting_noise after investigation.
        assert result.status == Status.VERIFIED


class TestCaptionInvestigationErrors:
    def test_investigate_caption_exception_falls_back_to_data_bug_warning(self):
        """When _investigate_caption itself raises an unexpected exception,
        the outer try/except in verify() records verdict=errored on the
        investigation stage and emits VERIFIED + cl_display_name_data_bug
        defensively. Status does NOT degrade to WRONG_CASE on infra failure.

        Per design v2 §2.4: status doesn't downgrade on infrastructure failure.

        Setup: client.get_cluster raises AttributeError (not caught by the
        inner per-step try/except which only catches generic Exception), which
        propagates out of _investigate_caption to the outer handler in verify().

        Actually: all exceptions are caught by the per-step try/except inside
        _investigate_caption. To test the outer fallback, we make the *overlap
        computation itself* fail by patching _party_overlap_ok to raise.

        Alternative approach: use a MagicMock that raises on the `get_cluster`
        return value's `.get()` call (so the exception occurs *inside* the step
        try block and is caught there). To test the outer handler, we instead
        patch `_investigate_caption` directly.
        """
        from unittest.mock import patch

        client = MagicMock()
        client.citation_lookup.return_value = [
            {
                "clusters": [
                    {
                        "case_name": "Different Caption",
                        "id": 1,
                        "absolute_url": "/opinion/1/",
                        "citations": [],
                    }
                ]
            }
        ]
        client.search_opinions.return_value = []
        client.search_recap.return_value = []
        client.get_docket_entries.return_value = []
        client.get_cluster.return_value = {}
        client.get_docket.return_value = {}
        client.get_opinion_text.return_value = None

        v = CitationVerifier(client)
        # Patch _investigate_caption to raise so the outer fallback fires.
        # Use "Hogan v. ATT" vs "Different Caption" — "hogan" and "att" are
        # not in "Different Caption" so _names_match_citation_lookup flags mismatch.
        with patch.object(v, "_investigate_caption", side_effect=RuntimeError("unexpected")):
            result = v.verify("Hogan v. ATT, 100 F.3d 200 (2d Cir. 2020)")

        # Investigation stage errored — defensive: VERIFIED + data-bug warning.
        assert result.status == Status.VERIFIED
        assert any(
            w.category == WarningCategory.cl_display_name_data_bug
            for w in result.warnings
        )
        inv = next(
            e for e in result.resolution_path
            if e.stage == StageName.caption_investigation
        )
        assert inv.verdict == StageVerdict.errored

    def test_individual_cl_call_failure_absorbed_returns_wrong_case(self):
        """When a single CL call inside _investigate_caption fails (e.g.
        get_cluster raises), the per-step try/except absorbs it and
        investigation continues with the remaining sources.

        If no party overlap is found across the remaining sources, the result
        is WRONG_CASE (not VERIFIED) — the investigation ran, it just couldn't
        find a match.

        This contrasts with the outer fallback: individual step failures are
        not infra failures — the investigation stage records verdict=resolved
        with notes about no overlap found.
        """
        client = MagicMock()
        client.citation_lookup.return_value = [
            {
                "clusters": [
                    {
                        "case_name": "Alpha v. Beta",
                        "id": 99,
                        "absolute_url": "/opinion/99/",
                        "citations": [],
                    }
                ]
            }
        ]
        client.search_opinions.return_value = []
        client.search_recap.return_value = []
        client.get_docket_entries.return_value = []
        # get_cluster fails → step 1 absorbed; docket_id=None → step 2 skipped;
        # get_opinion_text returns None → step 3 no text → no overlap → WRONG_CASE.
        client.get_cluster.side_effect = RuntimeError("API down")
        client.get_docket.return_value = {}
        client.get_opinion_text.return_value = None

        v = CitationVerifier(client)
        result = v.verify("Gamma v. Delta, 100 F.3d 200 (2d Cir. 2020)")
        # Investigation ran but found no overlap → WRONG_CASE, not VERIFIED.
        assert result.status == Status.WRONG_CASE
        inv = next(
            e for e in result.resolution_path
            if e.stage == StageName.caption_investigation
        )
        # The stage recorded a resolved verdict (the investigation completed,
        # just without finding an overlap).
        assert inv.verdict == StageVerdict.resolved
