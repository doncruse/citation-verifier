"""Verify false-negative CANDIDATES live under v0.3 before adding to corpus.

Each must verify (status != NOT_FOUND) and, where we expect an opinion,
resolve to the expected cluster_id. RECAP docket-only candidates have
cluster_id=None and are pinned by docket_id instead.
"""
from citation_verifier import CitationVerifier
from citation_verifier.models import Status

# (citation, expected_cluster_id or None, expected_docket_id or None, category, source)
CANDS = [
    ("Shaw v. Cooper, 32 U.S. 292 (1833)", 85831, None, "old_scotus", "benchmark"),
    ("Postell v. United States, 282 A.2d 551 (1971)", 1969207, None, "state_common_prefix_defendant", "benchmark"),
    ("Addis v. Steele, 648 N.E.2d 773 (1995)", 6585074, None, "state_reporter", "benchmark"),
    ("United States v. Straker, 800 F.3d 570 (2015)", 2832658, None, "common_prefix_plaintiff", "benchmark"),
    ("Brown v. Whole Foods Mkt. Grp., Inc., 789 F.3d 146 (2015)", 2807857, None, "standard_reporter", "benchmark"),
    ("Moore v. Hillman, No. 4:06-CV-43, 2006 WL 1313880 (W.D. Mich. May 12, 2006)", None, 4697246, "recap_no_court_paren", "master_csv"),
    ("Rosenthal v. Cnty. of Madison, 170 P.3d 493 (Mont. 2007)", 887862, None, "state_reporter_montana", "master_csv"),
    ("Marlite, Inc. v. Eckenrod, No. 10-23641-CIV, 2012 WL 3614212 (S.D. Fla. Aug. 22, 2012)", None, 4233374, "recap_filing_opinion_gap", "master_csv"),
]

v = CitationVerifier()
for cite, exp_cluster, exp_docket, cat, src in CANDS:
    r = v.verify(cite)
    fid = r.final_ids
    ok = r.status is not Status.NOT_FOUND and r.status is not Status.VERIFICATION_INCOMPLETE
    cl_ok = (exp_cluster is None) or (fid.cluster_id == exp_cluster)
    dk_ok = (exp_docket is None) or (fid.docket_id == exp_docket)
    verdict = "PASS" if (ok and cl_ok and dk_ok) else "CHECK"
    print(f"[{verdict}] {cat:32} {r.status.value:22} conf={r.headline_confidence}")
    print(f"        {cite[:74]}")
    print(f"        cluster={fid.cluster_id} (exp {exp_cluster})  docket={fid.docket_id} (exp {exp_docket})")
    print(f"        {fid.absolute_url}")
    print()
