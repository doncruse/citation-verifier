from citation_verifier.quote_matcher import (
    _best_match_with_passage,
    _normalize_ocr_confusions,
)


class TestNormalizeOcrConfusions:
    def test_rn_to_m_midword(self):
        assert _normalize_ocr_confusions("modern") == "modem"
        assert _normalize_ocr_confusions("concern") == "concem"

    def test_rn_not_word_initial(self):
        assert _normalize_ocr_confusions("rnage") == "rnage"

    def test_O_to_0_only_digit_adjacent(self):
        assert _normalize_ocr_confusions("O5") == "05"
        assert _normalize_ocr_confusions("5O") == "50"
        assert _normalize_ocr_confusions("Office") == "Office"

    def test_l_to_1_only_digit_adjacent(self):
        assert _normalize_ocr_confusions("l5") == "15"
        assert _normalize_ocr_confusions("5l") == "51"
        assert _normalize_ocr_confusions("liability") == "liability"

    def test_idempotent(self):
        for s in ["modern attorney", "O5 l5 5O", "no confusions here", "concern"]:
            once = _normalize_ocr_confusions(s)
            assert _normalize_ocr_confusions(once) == once

    def test_clean_text_with_no_gated_patterns_is_unchanged(self):
        s = "The court held that summary judgment was proper."
        assert _normalize_ocr_confusions(s) == s


class TestBestMatchOcr:
    def test_ocr_false_is_unchanged_default(self):
        # "modem" (true) vs an opinion that has the OCR'd "modern": no exact hit
        r_off, _ = _best_match_with_passage("modem device", "the modern device works")
        assert r_off < 1.0

    def test_ocr_true_collapses_to_verbatim(self):
        # Opinion text OCR'd "m" as "rn"; quote has the true "m"
        ratio, passage = _best_match_with_passage(
            "the modem device", "before the modern device after", ocr=True,
        )
        assert ratio == 1.0
        assert passage  # non-empty, sliced from the original haystack
        assert "device" in passage

    def test_ocr_true_clean_text_same_ratio_as_off(self):
        q = "summary judgment was proper"
        h = "the court held that summary judgment was proper here"
        on, _ = _best_match_with_passage(q, h, ocr=True)
        off, _ = _best_match_with_passage(q, h, ocr=False)
        assert on == off == 1.0

    def test_ocr_passage_in_bounds_with_collapses_before_match(self):
        # Many rn-words before the match must not throw / must stay in-bounds.
        prefix = "return concern attorney govern modern " * 20
        h = prefix + "the quoted phrase here"
        ratio, passage = _best_match_with_passage(
            "the quoted phrase here", h, ocr=True,
        )
        assert ratio == 1.0
        assert isinstance(passage, str) and passage != ""
