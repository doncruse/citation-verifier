from metrics import compute_metrics

METRIC_KEYS = ["n_cites", "words", "cite_density", "parenthetical_richness",
               "string_cite_rate", "gerund_paren_rate", "has_toa",
               "proposition_repeat_rate", "cite_prop_cv"]


def test_returns_full_vector():
    m = compute_metrics("Some text with no citations at all.")
    assert list(m.keys()) == METRIC_KEYS


def test_empty_text_is_safe():
    m = compute_metrics("")
    assert m["n_cites"] == 0
    assert m["cite_density"] == 0.0
    assert m["parenthetical_richness"] == 0.0
    assert m["proposition_repeat_rate"] == 0.0
    assert m["has_toa"] is False


def test_gerund_parenthetical_counts():
    # one citation, one gerund-led parenthetical
    txt = "The court agreed. Smith v. Jones, 500 U.S. 100 (2001) (holding that liability attaches)."
    m = compute_metrics(txt)
    assert m["n_cites"] >= 1
    assert m["gerund_paren_rate"] > 0.0


def test_proposition_repeat_detects_reshuffled_cites():
    # same proposition restated with a DIFFERENT citation -> a repeat pair
    txt = ("The statute bars retaliation against protected employees. "
           "Alpha v. Beta, 100 F.3d 200 (9th Cir. 1999). "
           "The statute bars retaliation against protected employees. "
           "Gamma v. Delta, 300 F.3d 400 (9th Cir. 2001).")
    m = compute_metrics(txt)
    assert m["proposition_repeat_rate"] > 0.0


def test_mph_fixture_pins_cite_count():
    # pins the current eyecite spine (matches GATE-RESULTS first run)
    raw = open("fixtures/support-community-mph--cand-63.md",
               encoding="utf-8", errors="replace").read()
    m = compute_metrics(raw)
    assert m["n_cites"] == 111
    assert m["cite_density"] > 0
    assert isinstance(m["has_toa"], bool)
