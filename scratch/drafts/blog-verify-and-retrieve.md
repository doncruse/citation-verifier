# Don't Trust. Verify. And Then Retrieve the Source.

*A free tool for checking legal citations against CourtListener*

---

I've spent the last several months building a citation verification tool. It started because I was getting frustrated. I kept seeing hallucination checkers that returned a lot of "unverified" cases — and I was certain that CourtListener had many of those decisions. The cases were real, but the checkers weren't finding them.

So I decided to build one that could.

The tool is called **Verify and Retrieve**, and it's [live on the web right now](https://verify-and-retrieve.replit.app/). All you need is a free CourtListener API key.

## The Problem

We all know the hallucination problem. I've written about [the science behind it](https://www.ailawlibrarians.com/2026/02/19/what-the-science-says-about-hallucinations-in-legal-research/), which confirms that, though general tools hallucinate more, even RAG-based legal research tools [can still hallucinate](https://www.ailawlibrarians.com/2024/04/19/rag-systems-can-still-hallucinate/). Courts have now documented over 1,000 cases where practitioners submitted AI-generated fake citations.

But if you've ever actually tried verifying citations, you know that the process is *tedious*. Manually typing each citation into a legal research tool takes a while.  Using a brief checker helps, but some of them can take 10-15 minutes to check the citations. I wanted something faster that would just quickly tell me if the case exists and give me the text.

But I ran into another problem - many citations are proprietary, meaning that they are produced by one legal research vendor or another, and then retrievable only from that platform. 

Shay Elbaum nailed this in his recent LIT-SIS post, ["Two Solutions for Hallucinated Citations to Unpublished Cases."](https://litsis.classcaster.net/2026/02/26/two-solutions-for-hallucinated-citations-to-unpublished-cases/) He starts from a point made — accidentally — by the attorney in *Flycatcher Corp. v. Affable Avenue LLC*: when a generative AI tool makes up citations in a proprietary format, it's difficult or impossible to verify them without access to the proprietary source. And on a quick review of recent fabricated citations, Elbaum found that many filings with fake citations included at least one in the `2022 WL 4637582` format, supposedly pointing to an unpublished case on Westlaw. As he puts it: if Westlaw doesn't want WL citations to become red flags for potential hallucinations, it needs to provide a method for everyone to verify them.

And indeed, the hallucination databases are full of examples of lawyers who didn't have access to Westlaw and had no way to check whether the WL cite that ChatGPT gave them even existed, let alone whether it supported their argument. I'm not excusing those attorneys — they should have verified before filing. But the walled gardens of legal information exacerbate the hallucination problem in a way that doesn't get enough attention. It's very difficult to validate a case when the citation itself is a proprietary key that only unlocks one vendor's door.

The underlying decisions that WL or Lexis citations point to are often already on CourtListener — they come from court websites, PACER, and the RECAP Archive. What CL *doesn't* have are the proprietary WL and Lexis citation numbers, because the vendors keep those under lock and key. So the decisions are there. You just can't look them up by WL number.

That's a big part of why I built a verification pipeline that goes beyond simple citation lookup. When a reporter citation doesn't match, the tool falls back to searching by case name, court, and date — and then searches RECAP docket entries for the actual documents. It's not as clean as typing in a WL number and getting a yes or no, but it finds cases that a simple citation lookup would miss. I'm not aware of other hallucination checkers that do this multi-step fallback, and in my testing it's the difference between flagging a real case as "not found" and actually finding it.

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

I should mention: I'm on the Free Law Project's board of directors. I started this project because I needed the tool, not because of the board role. But I'll be honest that working with CourtListener's data for months has only deepened my appreciation for what the Free Law Project has built. If you find the tool useful, consider [supporting FLP's work](https://free.law/donate/).

## What It Doesn't Do

A few things to be clear about:

**It doesn't tell you whether a case supports the proposition it's cited for.** That requires reading the opinion. What it *does* do is get that opinion into your hands quickly so you can read it yourself. (I've been building a [separate pipeline](https://github.com/rlfordon/citation-verifier) for proposition-level verification, but that's a story for another post, when I'm a bit further along.)

**It can't verify proprietary WL or Lexis citation numbers directly.** As I described above, CourtListener doesn't have those — but the tool flags them with a "WL Cite" badge so you know they need separate verification. When the brief also provides a case name, court, and date alongside the WL number, the Deep Search will try to find the decision anyway through the opinion and RECAP searches. It often succeeds. But a bare `2022 WL 4637582` with no other metadata is exactly the problem Elbaum describes — and until Westlaw and Lexis provide public verification, there's no free way to check it.

**It's not a substitute for professional legal research tools.** It's a verification layer. When a lawyer hands you a brief, or an LLM generates a memo, this tool answers the threshold question: *Do these cases exist, and can I get my hands on them?*

## How I Built It

I'll be honest: this is the biggest project I've coded in many, many years. It's a [vibe-coded](https://www.ailawlibrarians.com/2025/11/27/thanksgiving-vibe-coding-and-the-case-for-single-serving-legal-software/) project — I built it with Claude Code, iterating fast on real citations and real briefs. But "vibe coding" doesn't mean it was easy. Legal citations have an absurd number of edge cases, and I spent a lot of time testing, finding them, and fixing them. There were more than a few dumb mistakes along the way. It was challenging, and I learned a lot.

The core is a Python library that runs a three-step verification pipeline: citation lookup, opinion search, and RECAP search. The web app is a thin FastAPI wrapper with server-sent events for streaming results.

The citation parser combines [eyecite](https://github.com/freelawproject/eyecite) (an open-source citation extractor from the Free Law Project) with regex fallbacks for formats eyecite doesn't handle — California-style citations, Westlaw numbers, reversed parentheticals. Under the hood, there's a multi-factor name matcher that compares the case name you provide against what CourtListener returns, because even real citations can have slight name variations.

The entire codebase is [open source](https://github.com/rlfordon/citation-verifier).

## Who It's For

If you're a **law librarian** fielding questions about whether citations in an AI-generated memo are real — this is the fast check.

If you're a **legal writing professor** who wants students to verify their AI-assisted research — paste the citations and see what comes back.

If you're a **practitioner reviewing opposing counsel's brief** and something doesn't look right — check it in 10 seconds instead of 10 minutes.

If you're **anyone who's curious** whether a case citation is real — you don't need a Westlaw or Lexis subscription. You need a free CourtListener API key and this URL.

## Try It

1. Get a free account (or paid if you want to support FLP and get some [extra perks](https://donate.free.law/forms/membership)!) at [courtlistener.com](https://www.courtlistener.com/), then get your API key (Profile → Account → Developer Tools → Your API Token)
2. Go to [verify-and-retrieve.replit.app](https://verify-and-retrieve.replit.app/)
3. Enter your API key (stored locally in your browser — never sent to my server for logging)
4. Paste citations and hit Search

That's it. No account on my end, no subscription, no installation. Your API key stays in your browser's local storage.

If you find bugs, have ideas, or want to contribute, the [GitHub repo](https://github.com/rlfordon/citation-verifier) is open. And if this post leaves you wanting more on the hallucination detection side — stay tuned. Parts 2 and 3 of the hallucination series are still coming!
