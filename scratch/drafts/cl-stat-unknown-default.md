# Draft issue for CourtListener

## Target
https://github.com/freelawproject/courtlistener — new issue

## Title
Document stat_ filter parameters; consider inclusive default for API

## Body

### Summary

The opinion search API (`/api/rest/v4/search/?type=o`) defaults to returning only Published opinions when no `stat_` parameters are provided. The [API help page](https://www.courtlistener.com/help/api/rest/v4/search/) mentions this in passing ("only published results are returned by default"), but the `stat_` parameter names and values aren't documented — they're only discoverable by building a query on the website and inspecting the URL.

This affects both the website and the API. On the website, the status checkboxes at least make the filtering visible, but the default still excludes Unknown. On the API, there's no such signal — you get back a result set with no indication that anything was excluded.

The core issue is that the `recap_into_opinions` pipeline classifies ingested opinions as `precedential_status: Unknown`, and the search default hides Unknown. These two choices work against each other — CL puts significant effort into ingesting district court opinions from RECAP, but then the search defaults make them invisible to both website users and API consumers.

### How I ran into this

I'm building a citation verification tool that searches the API to check legal citations. I filed #6963 reporting 16 RECAP documents that appeared missing from the opinions database. After discovering `stat_Unknown`, I found that **10 of the 16 were actually present** — they had `precedential_status: Unknown` and were invisible to my searches. I'd read the API docs but missed the one sentence about the default, and had no way to know from the responses that results were being filtered.

The scale of what's hidden is significant. For S.D. Ohio alone:

| Query | Count |
|-------|-------|
| `type=o&court=ohsd` (default) | 4,923 |
| `type=o&court=ohsd&stat_Unknown=on` | 14,518 |

### Suggestions

1. **Document the `stat_` parameters** in the API reference with their values: `stat_Published`, `stat_Unpublished`, `stat_Unknown`, `stat_Errata`, `stat_Separate`, `stat_In-chambers`, `stat_Relating-to`
2. **Consider whether the API default should differ from the website default** — API consumers don't have the visual cue of unchecked boxes to tell them results are being filtered

### Related

- #6963 — 16 federal civil opinions exist in RECAP but not in the opinions database (10 were present with Unknown status)
