"""CITE_UNCONFIRMED classification, end-to-end (Check Cite design 2026-06-11 §3/§5.2).

Final rules (user-approved):

| evidence situation                              | outcome                              |
|-------------------------------------------------|--------------------------------------|
| cited location on the record                    | VERIFIED (unchanged)                 |
| same-family witness, address differs            | CITE_UNCONFIRMED + cite_contradicted |
| no same-family witness (CL gap / parallel / WL) | VERIFIED + cite_not_on_record warn   |
| RECAP, doc gate passed                          | VERIFIED_VIA_RECAP + warn            |
| RECAP, bare docket                              | CITE_UNCONFIRMED + cite_not_on_record|
| docket-number-cited (no reporter/WL cite)       | unchanged, no warning                |

Lookup/caption-investigation paths untouched (citation-anchored world).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from citation_verifier.models import Status, WarningCategory
from citation_verifier.verifier import CitationVerifier


def _make_client(**overrides):
    client = MagicMock()
    client.citation_lookup.return_value = overrides.get("citation_lookup", [])
    client.search_opinions.return_value = overrides.get("search_opinions", [])
    client.search_recap.return_value = overrides.get("search_recap", [])
    client.get_docket_entries.return_value = overrides.get("get_docket_entries", [])
    client.get_cluster.return_value = overrides.get("get_cluster", {})
    client.get_docket.return_value = overrides.get("get_docket", {})
    client.get_opinion_text.return_value = None
    client.get_opinion_text_with_metadata.return_value = None
    client.get_recap_document_metadata.return_value = overrides.get(
        "recap_document_metadata", None
    )
    return client


def _make_async_client(**overrides):
    client = AsyncMock()
    client.citation_lookup.return_value = overrides.get("citation_lookup", [])
    client.search_opinions.return_value = overrides.get("search_opinions", [])
    client.search_recap.return_value = overrides.get("search_recap", [])
    client.get_docket_entries.return_value = overrides.get("get_docket_entries", [])
    client.get_cluster.return_value = overrides.get("get_cluster", {})
    client.get_docket.return_value = overrides.get("get_docket", {})
    client.get_opinion_text.return_value = None
    client.get_opinion_text_with_metadata.return_value = None
    client.get_recap_document_metadata.return_value = overrides.get(
        "recap_document_metadata", None
    )
    return client


def _warning_categories(result):
    return {w.category for w in result.warnings}


# --- Opinion-search variant -------------------------------------------------

_TAYLOR_CITE = "Taylor v. State, 133 N.E.3d 708 (Ind. Ct. App. 2019)"


def _taylor_search_result(citations):
    return [{
        "caseName": "Taylor v. State",
        "id": 8278230,
        "absolute_url": "/opinion/8278230/taylor-v-state/",
        "dateFiled": "2019-09-09",
        "court_id": "indctapp",
        "citation": citations,
    }]


class TestOpinionSearchContradicted:
    """Bucket-B signature: real same-named case, same-family witness at a
    different address -> demote (Taylor v. State, Charlotin)."""

    def test_status_and_warning(self):
        client = _make_client(
            search_opinions=_taylor_search_result(["119 N.E.3d 1234"]),
        )
        v = CitationVerifier(client)
        result = v.verify(_TAYLOR_CITE)
        assert result.status == Status.CITE_UNCONFIRMED
        assert WarningCategory.cite_contradicted in _warning_categories(result)

    def test_final_ids_keep_winning_stage_shape(self):
        client = _make_client(
            search_opinions=_taylor_search_result(["119 N.E.3d 1234"]),
        )
        v = CitationVerifier(client)
        result = v.verify(_TAYLOR_CITE)
        assert result.final_ids.cluster_id == 8278230
        assert result.final_ids.text_source is not None
        assert result.final_ids.text_source.value == "opinion_plain_text"

    def test_contradiction_warning_carries_record_citations(self):
        """The warning details name CL's actual citations so consumers can
        render 'CL has this case at 119 N.E.3d 1234' (user-approved
        scarier-contradicted rendering)."""
        client = _make_client(
            search_opinions=_taylor_search_result(["119 N.E.3d 1234"]),
        )
        v = CitationVerifier(client)
        result = v.verify(_TAYLOR_CITE)
        warning = next(
            w for w in result.warnings
            if w.category == WarningCategory.cite_contradicted
        )
        assert warning.details is not None
        assert "119 N.E.3d 1234" in str(warning.details.get("record_citations"))

    def test_wrong_volume_real_case_also_contradicted(self):
        """Drywall-class typo: same evidence bucket as a fabrication --
        that's WHY the status only says 'check cite', not 'fake'."""
        client = _make_client(
            search_opinions=[{
                "caseName": "In re Chinese-Manufactured Drywall Products Liability Litigation",
                "id": 1234,
                "absolute_url": "/opinion/1234/drywall/",
                "dateFiled": "2010-10-14",
                "court_id": "laed",
                "citation": ["759 F. Supp. 2d 822"],
            }],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "In re Chinese-Manufactured Drywall Products Liability Litigation, "
            "742 F. Supp. 2d 672 (E.D. La. 2010)"
        )
        assert result.status == Status.CITE_UNCONFIRMED
        assert WarningCategory.cite_contradicted in _warning_categories(result)


class TestOpinionSearchNotOnRecord:
    """No same-family witness -> keep VERIFIED, attach cite_not_on_record
    (the user's reporter-gap compensation principle)."""

    def test_empty_record_citations_stays_verified_with_warning(self):
        client = _make_client(search_opinions=_taylor_search_result([]))
        v = CitationVerifier(client)
        result = v.verify(_TAYLOR_CITE)
        assert result.status == Status.VERIFIED
        assert WarningCategory.cite_not_on_record in _warning_categories(result)

    def test_cross_family_witness_stays_verified_with_warning(self):
        """Muldrow shape: cited S. Ct., record lists the U.S. parallel."""
        client = _make_client(
            search_opinions=[{
                "caseName": "Muldrow v. City of St. Louis",
                "id": 9633218,
                "absolute_url": "/opinion/9633218/muldrow/",
                "dateFiled": "2024-04-17",
                "court_id": "scotus",
                "citation": ["601 U.S. 346"],
            }],
        )
        v = CitationVerifier(client)
        result = v.verify("Muldrow v. City of St. Louis, 144 S. Ct. 967 (U.S. 2024)")
        assert result.status == Status.VERIFIED
        assert WarningCategory.cite_not_on_record in _warning_categories(result)

    def test_corroborated_stays_verified_without_warning(self):
        client = _make_client(
            search_opinions=_taylor_search_result(["133 N.E.3d 708"]),
        )
        v = CitationVerifier(client)
        result = v.verify(_TAYLOR_CITE)
        assert result.status == Status.VERIFIED
        assert WarningCategory.cite_not_on_record not in _warning_categories(result)
        assert WarningCategory.cite_contradicted not in _warning_categories(result)


# --- RECAP variant ----------------------------------------------------------

def _recap_docket(recap_documents):
    return [{
        "caseName": "Gibson v. Rosati",
        "docket_id": 5572677,
        "id": 5572677,
        "court_id": "nynd",
        "docket_absolute_url": "/docket/5572677/gibson-v-rosati/",
        "dateFiled": "2017-01-05",
        "docketNumber": "9:13-cv-00503",
        "recap_documents": recap_documents,
    }]


_GIBSON_CITE = "Gibson v. Rosati, 2017 WL 1155765 (N.D.N.Y. Mar. 27, 2017)"


class TestRecapBareDocketDemoted:
    """Bucket-C signature: WL cite matched nothing but a bare docket --
    no document, no text, nothing to check the cite OR the proposition
    against -> demote."""

    def test_status_warning_and_ids(self):
        client = _make_client(search_recap=_recap_docket([]))
        v = CitationVerifier(client)
        result = v.verify(_GIBSON_CITE)
        assert result.status == Status.CITE_UNCONFIRMED
        assert WarningCategory.cite_not_on_record in _warning_categories(result)
        assert result.final_ids.docket_id == 5572677
        assert result.final_ids.cluster_id is None
        assert result.final_ids.recap_document_id is None
        assert result.final_ids.text_source is None


class TestRecapDocGatePassedKeepsStatus:
    """Oracle/Abbott class (user ruling): a date-corroborated opinion-type
    document keeps VERIFIED_VIA_RECAP; the unverifiable WL cite becomes a
    warning, and the accepted cost is that date-gate-passing fakes keep
    this badge too."""

    def test_via_recap_with_warning(self):
        client = _make_client(
            search_recap=_recap_docket([{
                "id": 99887766,
                "entry_date_filed": "2017-03-27",
                "short_description": "DECISION AND ORDER OPINION",
                "page_count": 22,
                "is_free_on_pacer": True,
            }]),
        )
        v = CitationVerifier(client)
        result = v.verify(_GIBSON_CITE)
        assert result.status == Status.VERIFIED_VIA_RECAP
        assert WarningCategory.cite_not_on_record in _warning_categories(result)
        assert result.final_ids.recap_document_id == 99887766


class TestDocketNumberCitedRecapUnchanged:
    """A citation that gave a docket number and no reporter/WL cite is
    citation-checked BY the docket-number match -- no demotion, no warning."""

    def test_docket_only_no_reporter_cite_unchanged(self):
        results = _recap_docket([])
        client = _make_client(search_recap=results)
        v = CitationVerifier(client)
        result = v.verify("Gibson v. Rosati, No. 9:13-cv-00503 (N.D.N.Y. Mar. 27, 2017)")
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert WarningCategory.cite_not_on_record not in _warning_categories(result)
        assert WarningCategory.cite_contradicted not in _warning_categories(result)

    def test_wl_plus_matching_docket_number_keeps_docket_only(self):
        """Bare-docket exemption: a WL cite accompanied by a docket number
        that MATCHES the record keeps VERIFIED_DOCKET_ONLY (the docket
        number vouches for identity); the unverifiable WL cite becomes a
        warning."""
        client = _make_client(search_recap=_recap_docket([]))
        v = CitationVerifier(client)
        result = v.verify(
            "Gibson v. Rosati, No. 9:13-cv-00503, 2017 WL 1155765 "
            "(N.D.N.Y. Mar. 27, 2017)"
        )
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert WarningCategory.cite_not_on_record in _warning_categories(result)


# --- Async parity -----------------------------------------------------------

class TestAsyncParity:
    def test_async_contradicted(self):
        async_client = _make_async_client(
            search_opinions=_taylor_search_result(["119 N.E.3d 1234"]),
        )
        v = CitationVerifier(_make_client())
        result = asyncio.run(v.verify_async(async_client, _TAYLOR_CITE))
        assert result.status == Status.CITE_UNCONFIRMED
        assert WarningCategory.cite_contradicted in _warning_categories(result)

    def test_async_bare_docket(self):
        async_client = _make_async_client(search_recap=_recap_docket([]))
        v = CitationVerifier(_make_client())
        result = asyncio.run(v.verify_async(async_client, _GIBSON_CITE))
        assert result.status == Status.CITE_UNCONFIRMED
        assert WarningCategory.cite_not_on_record in _warning_categories(result)
