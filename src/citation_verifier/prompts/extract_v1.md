<!-- prompt_version: extract-v1 -->
<!-- Document-extraction prompt (design SS3 verb 0, SS2 input contract,
     SS6.3 cited_for, SS6.5 TOA/body lists). Sources: the verify-brief
     SKILL.md Phase 1a/1c rules, made deterministic as a versioned
     template. Any edit to this file is a NEW prompt version: copy to
     extract_v2.md, bump the header. Placeholder: {document_path}. -->
You are extracting case-citation claims from a legal document (brief, motion, or opinion) so each claim can be verified against the cited authority.

Read the document at: {document_path}

Use ONLY the Read tool on that file. Do not use web search, web fetch, bash, or any other tool. Do not rely on outside knowledge about any cited case.

Produce three outputs:

1. "claims" -- one entry per proposition-case pair in the document body:
   - "cited_case": the citation EXACTLY as the document cites it, starting with the case name and including the full reporter citation and year (e.g., "Camp v. Pitts, 411 U.S. 138, 142 (1973)"). Append pinpoint pages after the start page. Do NOT abbreviate, omit the reporter, or use short-form case names -- when the document uses a short form (id., supra, name-only), resolve it to the full citation given at first use.
   - "proposition": one sentence, in your words, stating the legal claim the document attributes to this case.
   - "cited_for": when a signal or parenthetical attributes a NARROWER assertion to this specific case than the surrounding sentence argues, state that narrower assertion; otherwise "".
   - "quoted_text": JSON array of the exact strings the document places inside quotation marks for this claim. [] if none.
   - "brief_sentence": the document's sentence(s) containing the citation, reproduced as written -- including quoted language, signal word, and any parenthetical. Normalize whitespace; do not paraphrase. You may trim with [...] keeping the cited-case fragment and immediate context.
   - "page": the page of the document where the claim appears (printed page number if visible, else PDF page), as a string.
   Rules: same case cited for different propositions = separate entries; one proposition supported by several cases = separate entries (one per case); case citations only -- exclude statutes, regulations, constitutional provisions, treatises, and other secondary sources.

2. "citations_toa" -- every case citation listed in the Table of Authorities, one entry per case, base citation without pinpoint, exactly as written. [] if the document has no Table of Authorities.

3. "citations_body" -- every unique case citation appearing in the document body, base citation without pinpoint, exactly as written, deduplicated. If the Table of Authorities and the body give different volumes or page numbers for the same case, include BOTH variants (one in each list, or both in citations_body if the TOA is absent).

Respond with ONLY a JSON object (no markdown fences, no commentary):
{"claims": [{"page": "...", "proposition": "...", "cited_for": "", "cited_case": "...", "quoted_text": [], "brief_sentence": "..."}], "citations_toa": ["..."], "citations_body": ["..."]}
