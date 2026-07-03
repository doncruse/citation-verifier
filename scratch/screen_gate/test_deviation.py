from run_gate import robust_z, deviation_flags, bad_doc_cells


def test_robust_z_zero_mad_is_zero():
    assert robust_z(100.0, 5.0, 0.0) == 0.0


def test_robust_z_scales_by_mad():
    # x=10, median=4, mad=1 -> (10-4)/(1.4826*1) ~= 4.047
    z = robust_z(10.0, 4.0, 1.0)
    assert 4.0 < z < 4.1


def test_deviation_flags_only_beyond_threshold():
    baseline = {
        "cite_density": {"median": 5.0, "mad": 1.0, "n": 12},
        "n_cites": {"median": 20.0, "mad": 4.0, "n": 12},
    }
    # cite_density wildly high, n_cites normal
    m = {"cite_density": 40.0, "n_cites": 21}
    flags = deviation_flags(m, baseline, z_thresh=3.5)
    assert "cite_density" in flags
    assert "n_cites" not in flags
    assert flags["cite_density"] > 0


def test_bad_doc_cells_covers_eleven():
    cells = bad_doc_cells()
    assert len(cells) == 11
    assert cells["stafford-taffet"] == "pro_se__merits_brief"
    assert cells["support-community-mph--cand-63"] == "attorney__merits_brief"
    assert set(cells.values()) <= {
        "attorney__merits_brief", "attorney__pleading", "attorney__procedural_motion",
        "pro_se__merits_brief", "pro_se__pleading", "pro_se__procedural_motion"}
