"""Deprecated alias: brief_pipeline is now proposition_pipeline (design §2).

sys.modules aliasing (not re-export) so that attribute patches against
citation_verifier.brief_pipeline (e.g. test_brief_pipeline's
@patch("citation_verifier.brief_pipeline.CitationVerifier")) reach the
globals the executing code actually reads. Remove after one minor version.
"""
import sys

from . import proposition_pipeline as _pp

sys.modules[__name__] = _pp
