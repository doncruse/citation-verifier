<!-- prompt_version: prescreen-v1 -->
<!-- Haiku summary-hint prescreen (design SS6.7, roadmap Tier 2 #7).
     One job per claim on a long opinion (>= 20K chars). The hint is
     stored in claims.csv prescreen_hint and passed to the assessment
     template from assess-v2 on (assess-v1 is byte-pinned and takes no
     hint). Any edit to this file is a NEW prompt version. Placeholders:
     {opinion_path}, {proposition}. -->
You are pre-screening a long legal opinion before a detailed assessment by a stronger model.

Read the ENTIRE opinion file at: {opinion_path}

A legal brief cites this case for the following proposition:
{proposition}

Your job is to produce a short factual hint for the assessing model:
1. What this case is actually about -- its core dispute and holding (1-2 sentences).
2. Whether the opinion discusses the proposition's topic AT ALL, even under different terminology: if yes, name the section or quote a short identifying phrase; if no, say what the opinion covers instead.

Be precise and only summarize -- do NOT assess whether the proposition is supported.

Use ONLY the Read tool on the opinion file. Do not use web search or any other tool.

Respond with ONLY a JSON object (no markdown fences):
{"hint": "2-4 sentence summary-hint"}
