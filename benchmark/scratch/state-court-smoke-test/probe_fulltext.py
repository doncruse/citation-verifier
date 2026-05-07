"""Re-probe full-text coverage for the smoke-test sample, checking ALL
opinion content fields (plain_text + html variants + xml_harvard).

The v1 pipeline's `get_opinion_text` only fetches `plain_text`, which is
near-zero for many state-court clusters. This probe answers: "is the
opinion's text reachable *in any form*?" — that's the v1.3-relevant
question.

Output: results.json updated in place with new fields:
  has_plain_text, has_html, has_xml, best_text_chars, best_format
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from citation_verifier.client import CourtListenerClient

HERE = Path(__file__).parent
RESULTS = HERE / "results.json"

MIN_SUBSTANTIVE_CHARS = 500


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str):
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str):
        if self._skip_depth == 0 and data:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    if not html:
        return ""
    p = _TextExtractor()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return ""
    txt = "".join(p.parts)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def probe_cluster(client: CourtListenerClient, cluster_id: int) -> dict:
    info = {
        "has_plain_text": False,
        "has_html": False,
        "has_xml": False,
        "best_text_chars": 0,
        "best_format": "",
    }
    try:
        cluster_resp = client._request_with_retry(
            "GET", f"{client.BASE_URL}/clusters/{cluster_id}/",
        )
        cluster = cluster_resp.json()
    except Exception as exc:
        info["error"] = str(exc)
        return info

    for op_url in cluster.get("sub_opinions", []) or []:
        try:
            op = client._request_with_retry("GET", op_url).json()
        except Exception:
            continue

        plain = (op.get("plain_text") or "").strip()
        if plain:
            info["has_plain_text"] = True
            if len(plain) > info["best_text_chars"]:
                info["best_text_chars"] = len(plain)
                info["best_format"] = "plain_text"

        for html_field in (
            "html_with_citations", "html", "html_lawbox",
            "html_columbia", "html_anon_2020",
        ):
            html = op.get(html_field) or ""
            if html.strip():
                info["has_html"] = True
                txt = html_to_text(html)
                if len(txt) > info["best_text_chars"]:
                    info["best_text_chars"] = len(txt)
                    info["best_format"] = html_field

        xml = op.get("xml_harvard") or ""
        if xml.strip():
            info["has_xml"] = True
            txt = html_to_text(xml)
            if len(txt) > info["best_text_chars"]:
                info["best_text_chars"] = len(txt)
                info["best_format"] = "xml_harvard"

    return info


def main() -> None:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    client = CourtListenerClient()
    client.REQUEST_TIMEOUT = 30

    n_with_cluster = 0
    for i, r in enumerate(results):
        cid = r.get("matched_cluster_id")
        if not cid:
            continue
        n_with_cluster += 1
        print(f"[{i+1}/{len(results)}] cluster {cid}", end=" ")
        info = probe_cluster(client, cid)
        r.update(info)
        print(f"-> {info['best_format']} ({info['best_text_chars']} chars)")

    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    n = len(results)
    name_match = sum(1 for r in results
                     if r.get("v_status") in ("VERIFIED", "LIKELY_REAL"))
    courtsdb_resolvable = sum(1 for r in results if r.get("courtsdb_system"))
    full_text_any = sum(
        1 for r in results
        if (r.get("best_text_chars") or 0) >= MIN_SUBSTANTIVE_CHARS
    )
    plain_only = sum(
        1 for r in results
        if (r.get("opinion_chars") or 0) >= MIN_SUBSTANTIVE_CHARS
    )

    print()
    print(f"Sample size: {n}")
    print(f"Name-match (VERIFIED/LIKELY_REAL): {name_match}/{n} ({name_match/n:.0%})")
    print(f"Court resolvable in courts-db:    {courtsdb_resolvable}/{n} ({courtsdb_resolvable/n:.0%})")
    print(f"Full-text via plain_text only:    {plain_only}/{n} ({plain_only/n:.0%})")
    print(f"Full-text via any format >=500:   {full_text_any}/{n} ({full_text_any/n:.0%})")


if __name__ == "__main__":
    main()
