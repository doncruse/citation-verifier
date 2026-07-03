from compute_baselines import mad, cell_baseline, CELLS


def test_cells_are_six_canonical():
    assert set(CELLS) == {
        "attorney__merits_brief", "attorney__pleading", "attorney__procedural_motion",
        "pro_se__merits_brief", "pro_se__pleading", "pro_se__procedural_motion",
    }


def test_mad_basic():
    # values 1,2,4,4,5 -> median 4 -> abs devs 3,2,0,0,1 -> median 1
    assert mad([1, 2, 4, 4, 5]) == 1.0


def test_mad_empty_is_zero():
    assert mad([]) == 0.0


def test_cell_baseline_shape_and_values():
    rows = [
        {"n_cites": 10, "cite_density": 5.0},
        {"n_cites": 20, "cite_density": 7.0},
        {"n_cites": 30, "cite_density": 9.0},
    ]
    b = cell_baseline(rows)
    assert b["n_cites"]["median"] == 20
    assert b["n_cites"]["n"] == 3
    assert b["cite_density"]["median"] == 7.0
    assert "mad" in b["n_cites"]
