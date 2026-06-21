# LQ.AI roundtable — prep sheet

**Event:** LQ.AI roundtable — "introduce LQ.AI + next steps + how to contribute." ~2 days out — *[fill in exact date/time; likely Discord per the contributor guide].*

**Your goal:** be seen as the **hybrid** (legal *and* builder), surface the verification / research-quality gap, and start the relationship — especially with Kevin. Not to win an argument; to be known and open doors.

**Mindset (read right before you join):**
- It's a **bounty board.** DE-279 is a *posted* bounty — claiming it is welcomed, not intruding.
- You're at **day ~1.5 of their ~7-day** response window. Nothing's been ignored.
- You're the rare person who can **build the verification engine *and* attest to it** ("attestation is the deliverable — agents can't attest"). You belong in this room.

---

## Self-intro (~30 sec)

> "I'm Rebecca — law librarian and former bankruptcy attorney, and I'm on the Free Law Project board (FLP runs CourtListener), here in a personal capacity. I've built a Python citation-verification pipeline against the CourtListener API — it checks whether case citations are *real*, whether quotes are *accurate*, and whether a cited case actually *supports the proposition* it's cited for. So I'm happy to work the Backend+Legal and AI/ML+Legal bounties, not just the attestation ones."

*Why:* repositions you from "a lawyer who can review" → "builds the verification layer *and* can vouch for it." Don't let "attorney" slot you into the attestation-only lane.

## Warm opener for Kevin (turns the worry into an ally)

> "I came across Legal-Week-Cite-Checker — nice that you'd already built citation-checking against CourtListener. I've been working the same problem in Python from a different angle; I'd love to compare notes."

## Three things to land — *if the moment's right* (offers, not lectures)

1. **I've claimed DE-279** (issue #173) — happy to do the Python port; a small, surgical first slice on top of the CourtListener tool you already shipped.
2. **The research-quality layer is the least-planned, highest-value piece** — is the citation real, does the case support the claim. I've built exactly this and can bring it.
3. **Worth deciding early:** is the case-law research skill (6d) *one* skill, or a **decomposed set of skills + an orchestrator**? (Raise as a question — it's a "discuss-first" item per the guide.)

## Better than talking — *ask these* (opens doors, shows you get it)

- "What's the plan for the research-quality / verification layer — DE-279 and DE-280? Near-term, or deferred?"
- "Is the case-law research skill (6d) conceived as one skill, or decomposed with an orchestrator?"
- "For the gold sets and skill acceptance tests where attorney attestation is the deliverable — how do you want that to flow from a contributor?"

## Tone / watch-outs

- It's an **intro session** → listen first, offer don't impose. Plant the architecture point as a *question*, not a monologue.
- **Don't** lead with "you ignored my issue" — it's day 1.5; that reads as impatience and you don't need it.
- **Don't** let "attorney" pigeonhole you — lead **hybrid**.
- The skills-vs-orchestrator architecture is a **"discuss-first"** topic (their guide) → the roundtable *is* that venue. Float it live; if there's interest, follow with a GitHub Discussion.

## Do before the call (2 min)

Post on **#173** to make the claim explicit *and* show you're tracking their sprint:

> I'd like to claim DE-279 and take this on. Quick note since the area's moving fast: the governed chat tool-loop (#187) and external-source provenance (#191) both landed since I filed. #191's `message_tool_sources` is retrieval-provenance ("cases consulted"), deliberately separate from verification — so this name-check still fills the gap: a turn can consult real cases and *still* emit a fabricated case name. Happy to align on the open questions before I build.

Have handy: issue #173 · github.com/rlfordon/citation-verifier · this sheet.
