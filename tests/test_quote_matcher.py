from citation_verifier.quote_matcher import _normalize_ocr_confusions


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
