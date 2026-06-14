<!-- prompt_version: assess-v1 -->
<!-- The established single-claim assessment prompt: byte-identical when
     rendered to tests/ab_test_runner.py::build_prompt and
     tests/measure_withers_assessment.py::build_prompt (the prompt every
     recorded assess-v1 cassette was produced with). Any edit to this file
     is a NEW prompt version: copy to assess_v2.md, bump the header, and
     re-record the corpora cassettes. Placeholders: {opinion_path},
     {cited_case}, {proposition}, {quote_check_worst}. -->
You are assessing whether a case citation in a legal brief supports the proposition it is cited for.

Read the opinion file at: {opinion_path}

Cited case: {cited_case}
Proposition: {proposition}
Quote check result: {quote_check_worst}

Assessment criteria:
- Green: case directly and accurately supports the proposition
- Yellow: partially relevant, support weaker than represented, or proposition overstates the holding
- Red: does not support, misleading, case addresses a completely different topic, or quoted language is fabricated

If the quote check is FABRICATED, downgrade to at least Yellow.

Respond with ONLY a JSON object (no markdown, no explanation):
{"assessment": "Green|Yellow|Red", "rationale": "one sentence"}
