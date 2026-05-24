"""Tests documenting CourtListener API limitations and workarounds.

These tests validate:
1. Known API issues are still present (or have been fixed by FLP)
2. Our workarounds are still needed (or can be removed)
3. Documentation of issues for potential FLP contribution

Run with: pytest tests/test_cl_api_issues.py -v -s
"""

import json
from pathlib import Path

import pytest

from citation_verifier.client import CourtListenerClient


_DATA_DIR = Path(__file__).parent / "data"
_ISSUES_FILE = _DATA_DIR / "cl_api_issues.json"


def load_api_issues():
    """Load documented API issues."""
    if not _ISSUES_FILE.exists():
        return []
    with open(_ISSUES_FILE) as f:
        return json.load(f)


class TestAbbreviationMatching:
    """Tests for abbreviation matching in search.

    Related FLP issues:
    - https://github.com/freelawproject/courtlistener/issues/3089
    - https://github.com/freelawproject/courtlistener/issues/3367

    Expected: CL should match "Cnty." to "County", "Dep't" to "Department"
    Actual: No match unless we normalize first
    """

    @pytest.mark.skip(reason="Known API limitation - tracked in cl_api_issues.json")
    def test_cnty_abbreviation_search(self):
        """Search should match 'Cnty.' to 'County'."""
        client = CourtListenerClient()

        # Search for case with abbreviated name
        results = client.search_recap(case_name="Bossart v. King Cnty.")

        # Should find the case (CL has "Bossart v. King County")
        assert len(results) > 0, (
            "CL search doesn't match 'Cnty.' to 'County'. "
            "This is a known limitation - we normalize client-side."
        )

        # Verify it's the right case
        found_bossart = any(
            "Bossart" in r.get("caseName", "") for r in results
        )
        assert found_bossart, "Expected to find Bossart case"

    @pytest.mark.skip(reason="Known API limitation - tracked in cl_api_issues.json")
    def test_dept_abbreviation_search(self):
        """Search should match 'Dep't' to 'Department'."""
        client = CourtListenerClient()

        # Search for case with abbreviated name
        results = client.search_recap(
            case_name="Busha v. SC Dep't of Mental Health"
        )

        # Should find the case (CL has "Busha v. SC Department of Mental Health")
        assert len(results) > 0, (
            "CL search doesn't match 'Dep't' to 'Department'. "
            "This is a known limitation - we normalize client-side."
        )

    def test_our_abbreviation_workaround(self):
        """Our normalization workaround should find abbreviated cases."""
        from citation_verifier import CitationVerifier

        verifier = CitationVerifier()

        # Our parser normalizes before searching
        result = verifier.verify(
            "Bossart v. King Cnty., Case No. 2:24-cv-01776-JHC, "
            "2025 WL 459154 (W.D. Wash. Feb. 11, 2025)"
        )

        # Should find it via our normalization. Phase 2: each stage
        # emits its own path entry, so look across the resolved entries
        # for the matched case name (citation_lookup uses
        # ``matched_case_name``; opinion_search / recap_*_search use
        # ``best_case_name``).
        from citation_verifier.models import StageVerdict
        matched_case_name = None
        for entry in result.resolution_path:
            if entry.verdict != StageVerdict.resolved:
                continue
            summary = entry.raw_response_summary
            candidate = (
                summary.get("matched_case_name")
                or summary.get("best_case_name")
                or summary.get("case_name")
            )
            if candidate:
                matched_case_name = candidate
                break
        assert matched_case_name is not None
        assert "Bossart" in matched_case_name
        print(f"\n[OK] Found via normalization: {matched_case_name}")


class TestDocketParameterReliability:
    """Tests for RECAP search 'docket' parameter.

    Issue: The 'docket' param appears to be ignored by the API
    Workaround: Use 'q' with quoted docket number, filter client-side
    """

    @pytest.mark.skip(reason="Known API bug - tracked in cl_api_issues.json")
    def test_docket_param_filters_results(self):
        """The 'docket' param should filter to matching dockets."""
        client = CourtListenerClient()

        # This uses the 'docket' param (which doesn't work)
        # We've already switched to 'q' workaround, so need to test differently
        import time
        time.sleep(1)

        params = {"type": "r", "docket": "C15-1228"}
        resp = client._session.get(
            f"{client.BASE_URL}/search/",
            params=params,
            timeout=client.REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])

        # Should return only dockets matching C15-1228
        for r in results:
            docket_num = r.get("docketNumber", "")
            assert "15-1228" in docket_num or "C15-1228" in docket_num, (
                f"API returned unrelated docket: {docket_num}\n"
                "The 'docket' param appears to be ignored."
            )

    def test_our_docket_workaround(self):
        """Our 'q' parameter workaround should work."""
        client = CourtListenerClient()

        # Our workaround uses 'q' with quoted docket number
        results = client.search_recap(docket_number="C15-1228-JCC")

        # Should get some results (may include fuzzy matches)
        assert len(results) > 0, "No results from docket search"

        print(f"\n[OK] Docket search returned {len(results)} results")
        print("First 3 dockets:")
        for r in results[:3]:
            print(f"  - {r.get('docketNumber', 'N/A')}: {r.get('caseName', 'N/A')}")

        # Our verifier then filters to actual matches
        from citation_verifier.verifier import CitationVerifier
        v = CitationVerifier()
        normalized_cited = v._normalize_docket_number("C15-1228-JCC")

        filtered = [
            r for r in results
            if v._normalize_docket_number(r.get("docketNumber", "")) == normalized_cited
        ]

        print(f"\nAfter client-side filtering: {len(filtered)} exact matches")


class TestAPIIssueDocumentation:
    """Meta-tests to ensure API issues are documented."""

    def test_issues_file_exists(self):
        """cl_api_issues.json should exist and be valid."""
        assert _ISSUES_FILE.exists(), (
            f"API issues file missing: {_ISSUES_FILE}\n"
            "Create it to track known CL API limitations."
        )

        issues = load_api_issues()
        assert len(issues) > 0, "API issues file is empty"

        # Validate structure
        required_fields = [
            "issue_type", "status", "severity", "description",
            "our_workaround", "upstream_fix_needed"
        ]

        for i, issue in enumerate(issues):
            for field in required_fields:
                assert field in issue, (
                    f"Issue {i} missing required field: {field}"
                )

    def test_print_issues_summary(self):
        """Print summary of tracked API issues."""
        issues = load_api_issues()

        print("\n" + "="*70)
        print("COURTLISTENER API ISSUES TRACKING")
        print("="*70)

        by_status = {}
        for issue in issues:
            status = issue.get("status", "unknown")
            by_status.setdefault(status, []).append(issue)

        for status in ["confirmed", "known_flp_issue", "data_quality", "known_limitation"]:
            if status not in by_status:
                continue

            print(f"\n{status.upper().replace('_', ' ')}:")
            for issue in by_status[status]:
                severity = issue.get("severity", "?")
                issue_type = issue.get("issue_type", "?")
                print(f"  [{severity:6s}] {issue_type}")
                print(f"           {issue.get('description', '')[:60]}...")

                workaround = issue.get("our_workaround", "")
                if workaround:
                    print(f"           Workaround: {workaround[:60]}...")

                flp_issues = issue.get("related_flp_issues", [])
                if flp_issues:
                    print(f"           FLP issues: {', '.join(flp_issues)}")
                print()

        print("="*70)
        print(f"Total tracked issues: {len(issues)}")
        print("="*70)

    def test_suggest_flp_contributions(self):
        """Suggest which issues to report to FLP."""
        issues = load_api_issues()

        need_reporting = [
            issue for issue in issues
            if issue.get("status") == "confirmed"
            and not issue.get("related_flp_issues")
        ]

        print("\n" + "="*70)
        print("SUGGESTED FLP ISSUE REPORTS")
        print("="*70)

        if not need_reporting:
            print("\nNo new issues to report - all tracked issues either:")
            print("  - Already reported to FLP")
            print("  - Known limitations (won't be fixed)")
            print("  - Need more examples before reporting")
        else:
            print("\nThese issues should be reported to FLP:\n")
            for issue in need_reporting:
                print(f"Issue: {issue.get('issue_type')}")
                print(f"  Severity: {issue.get('severity')}")
                print(f"  Description: {issue.get('description')}")
                print(f"  Upstream fix: {issue.get('upstream_fix_needed')}")

                examples = issue.get("examples", [])
                if examples:
                    print(f"  Examples: {len(examples)} documented")
                print()

        print("="*70)
