# Don't Trust. Verify. And Then Retrieve the Source.

*A free tool for checking legal citations against CourtListener*

---

I've spent the last several months building a citation verification tool. It started as a way to answer a simple question: *Is this case real?* It turned into something I use almost every day.

The tool is called **Verify and Retrieve**, and it's [live on the web right now](https://verify-and-retrieve.replit.app/). All you need is a free CourtListener API key.

## The Problem

We all know the hallucination problem. I wrote about the [science behind it](https://www.ailawlibrarians.com/2026/02/19/what-the-science-says-about-hallucinations-in-legal-research/) back in February — hallucination rates in general-purpose models range from 58% to 88% on legal questions, and even RAG-based legal research tools [can still hallucinate](https://www.ailawlibrarians.com/2024/04/19/rag-systems-can-still-hallucinate/). Courts have now documented nearly 1,000 cases where practitioners submitted AI-generated fake citations.

But here's the thing that kept bugging me: *verifying* a citation is tedious. You have to go look it up. If you have a brief with 50 citations, you're doing that 50 times. And if a citation doesn't come up, you can't always tell whether the case doesn't exist or whether you just searched for it wrong.

I wanted something that could take a list of citations, check them all, and hand me back the actual opinions — so I could read the source material myself, not just trust that it exists.

## What It Does

You paste citations into a text box, one per line:

```
Obergefell v. Hodges, 576 U.S. 644 (2015)
Miranda v. Arizona, 384 U.S. 436 (1966)
Terry v. Ohio, 392 U.S. 1 (1968)
```

Hit **Search**, and the tool checks each one against CourtListener's database. Results stream in as they're verified — you get a status badge for each citation:

- **Ready** (green) — citation verified, opinion available for download
- **Check Name/Court/Date** (yellow) — something was found at that reporter citation, but the details don't quite match. Worth a manual look.
- **Not Found** (red) — no match in CourtListener's database

The first pass is fast — it uses CourtListener's citation lookup API in batch, so verifying 50 citations takes a few seconds. If some come back empty, a **Deep Search** button appears. Deep Search runs a fuzzy name-and-date search plus a RECAP (PACER) docket search for the misses. It's slower, but it catches cases that exist under slightly different citations or spellings.

Once you have your results, check the boxes next to the cases you want and download them in bulk — as plain text (best for feeding to an LLM), HTML (formatted with footnotes), or PDFs (best for reading).

## Why CourtListener?

[CourtListener](https://www.courtlistener.com/) is a free, open legal research database run by the [Free Law Project](https://free.law/), a nonprofit. It has millions of opinions, and it's the backbone behind the RECAP Archive — the largest free collection of PACER documents. The API is free, well-maintained, and designed for exactly this kind of programmatic access.

I should mention: I'm on the Free Law Project's board of directors. I started this project because I needed the tool, not because of the board role — but I'll be honest that working with CourtListener's data for months has only deepened my appreciation for what the Free Law Project has built. If you find the tool useful, consider [supporting FLP's work](https://free.law/donate/).

## What It Doesn't Do

A few things to be clear about:

**It doesn't tell you whether a case supports the proposition it's cited for.** That requires reading the opinion. What it *does* do is get that opinion into your hands quickly so you can read it yourself. (I've been building a [separate pipeline](https://github.com/rlfordon/citation-verifier) for proposition-level verification, but that's a story for another post.)

**It doesn't cover everything.** CourtListener is comprehensive, but it doesn't have every case ever published. Westlaw citations (like `2018 WL 301424`) can't be verified because CourtListener doesn't track WL numbers — those get flagged with a "WL Cite" badge so you know to check them elsewhere. Unreported decisions and very recent opinions may also be missing.

**It's not a substitute for professional legal research tools.** It's a verification layer. When a lawyer hands you a brief, or an LLM generates a memo, this tool answers the threshold question: *Do these cases exist, and can I get my hands on them?*

## How I Built It

This is a [vibe-coded](https://www.ailawlibrarians.com/2025/11/27/thanksgiving-vibe-coding-and-the-case-for-single-serving-legal-software/) project in the best sense — I built it with Claude Code, iterating fast on real citations and real briefs. The core is a Python library that runs a three-step verification pipeline: citation lookup, opinion search, and RECAP search. The web app is a thin FastAPI wrapper with server-sent events for streaming results.

The citation parser combines [eyecite](https://github.com/freelawproject/eyecite) (an open-source citation extractor from the Free Law Project) with regex fallbacks for formats eyecite doesn't handle — California-style citations, Westlaw numbers, reversed parentheticals. Under the hood, there's a multi-factor name matcher that compares the case name you provide against what CourtListener returns, because even real citations can have slight name variations.

The entire codebase is [open source](https://github.com/rlfordon/citation-verifier).

## Who It's For

If you're a **law librarian** fielding questions about whether citations in an AI-generated memo are real — this is the fast check.

If you're a **legal writing professor** who wants students to verify their AI-assisted research — paste the citations and see what comes back.

If you're a **practitioner reviewing opposing counsel's brief** and something doesn't look right — check it in 10 seconds instead of 10 minutes.

If you're **anyone who's curious** whether a case citation is real — you don't need a Westlaw or Lexis subscription. You need a free CourtListener API key and this URL.

## Try It

1. Get a free API key at [courtlistener.com](https://www.courtlistener.com/) (Profile → API Keys)
2. Go to [verify-and-retrieve.replit.app](https://verify-and-retrieve.replit.app/)
3. Enter your API key (stored locally in your browser — never sent to my server for logging)
4. Paste citations and hit Search

That's it. No account on my end, no subscription, no installation. Your API key stays in your browser's local storage.

If you find bugs, have ideas, or want to contribute, the [GitHub repo](https://github.com/rlfordon/citation-verifier) is open. And if this post leaves you wanting more on the hallucination detection side — stay tuned. Parts 2 and 3 of the hallucination series are coming.

---

*Rebecca Fordon is a Reference Librarian and Adjunct Professor at The Ohio State University Moritz College of Law, where she teaches legal research, legal writing, and legal technology. She is a board member of the Free Law Project.*
