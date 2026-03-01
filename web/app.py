"""Citation Verifier web application — FastAPI + SSE streaming."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import random
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
import certifi
import ssl as _ssl
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from citation_verifier.cache import VerificationCache
from citation_verifier.client import AsyncCourtListenerClient
from citation_verifier.models import ParsedCitation, VerificationResult, VerificationStatus
from citation_verifier.name_matcher import CaseNameMatcher
from citation_verifier.verifier import CitationVerifier

logger = logging.getLogger(__name__)

MAX_CITATIONS = 50


def _get_api_token(request: Request) -> str | None:
    """Extract CourtListener API token from request header (BYOK)."""
    return request.headers.get("X-CL-API-Token") or None

# Paths
_project_root = Path(__file__).parent.parent
_results_dir = _project_root / "tests" / "data" / "results"
_default_csv = _project_root / "scratch" / "citations_for_review.csv"


# ---------------------------------------------------------------------------
# MasterCSV — lazy-loading CSV helper with QC read/write and dupe detection
# ---------------------------------------------------------------------------

class MasterCSV:
    """Lazy-loading wrapper around the master citations CSV."""

    def __init__(self, csv_path: Path | None = None):
        self._path = csv_path or _default_csv
        self._rows: list[dict] | None = None
        self._fieldnames: list[str] = []
        self._mtime: float = 0.0
        self._matcher = CaseNameMatcher()

    def _load(self) -> None:
        """Load (or reload) the CSV if the file has changed."""
        try:
            current_mtime = self._path.stat().st_mtime
        except OSError:
            self._rows = []
            self._fieldnames = []
            return
        if self._rows is not None and current_mtime == self._mtime:
            return
        with open(self._path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self._fieldnames = list(reader.fieldnames or [])
            self._rows = list(reader)
        self._mtime = current_mtime

    @property
    def rows(self) -> list[dict]:
        self._load()
        return self._rows or []

    def get_row(self, citation_text: str) -> dict | None:
        """Find a row by exact citation_text match."""
        for row in self.rows:
            if row.get("citation_text", "").strip() == citation_text.strip():
                return row
        return None

    def update_qc(
        self, citation_text: str, qc_status: str, qc_notes: str
    ) -> bool:
        """Update qc_status and qc_notes for a citation row. Returns True on success."""
        self._load()
        if not self._rows:
            return False

        target = citation_text.strip()
        found = False
        for row in self._rows:
            if row.get("citation_text", "").strip() == target:
                row["qc_status"] = qc_status
                row["qc_notes"] = qc_notes
                found = True
                break

        if not found:
            return False

        # Backup then write
        bak = self._path.with_suffix(".csv.bak")
        shutil.copy2(self._path, bak)

        with open(self._path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._fieldnames)
            writer.writeheader()
            for row in self._rows:
                writer.writerow(row)

        self._mtime = self._path.stat().st_mtime
        return True

    def find_duplicates(
        self,
        case_name: str | None,
        volume: str | None,
        reporter: str | None,
        page: str | None,
        exclude_citation: str | None = None,
    ) -> list[dict]:
        """Find potential duplicate rows using name similarity and volume/reporter/page proximity."""
        dupes: list[dict] = []
        exclude = (exclude_citation or "").strip()

        for row in self.rows:
            row_cite = row.get("citation_text", "").strip()
            if row_cite == exclude:
                continue
            # Only compare against rows that have been verified
            if not row.get("v_status"):
                continue

            score = 0.0
            reason = ""

            # Name similarity
            row_name = row.get("case_name", "")
            if case_name and row_name:
                name_sim = self._matcher.calculate_similarity(case_name, row_name)
                if name_sim >= 0.75:
                    score = max(score, name_sim)
                    reason = "name"

            # Volume+reporter+page proximity
            if (
                volume and reporter and page
                and row.get("volume") == volume
                and row.get("reporter") == reporter
            ):
                try:
                    page_diff = abs(int(page) - int(row.get("page", "0")))
                except (ValueError, TypeError):
                    page_diff = 9999
                if page_diff == 0:
                    score = max(score, 0.99)
                    reason = "exact_cite"
                elif page_diff <= 50:
                    score = max(score, 0.92)
                    reason = "pin_cite"

            if score >= 0.75:
                dupes.append({
                    "citation_text": row_cite,
                    "case_name": row_name,
                    "v_status": row.get("v_status", ""),
                    "qc_status": row.get("qc_status", ""),
                    "similarity": round(score, 3),
                    "reason": reason,
                    "tier": "high" if score >= 0.90 else "possible",
                })

        # Sort by similarity descending
        dupes.sort(key=lambda d: d["similarity"], reverse=True)
        return dupes[:10]


app = FastAPI(title="Citation Verifier", version="0.1.0")

# Public mode: when MODE=public, only serve the Get & Print page (for Replit).
_public_mode = os.environ.get("MODE", "").lower() == "public"

if _public_mode:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response as StarletteResponse

    class _BlockQCMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            if path == "/qc" or path.startswith("/api/qc"):
                return StarletteResponse("Not Found", status_code=404)
            return await call_next(request)

    app.add_middleware(_BlockQCMiddleware)

# Mount static files
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Shared instances
_cache = VerificationCache()
_verifier = CitationVerifier()
_master_csv = MasterCSV()


def _result_to_dict(result: VerificationResult) -> dict[str, Any]:
    return {
        "input_citation": result.input_citation,
        "status": result.status.value,
        "confidence": result.confidence,
        "matched_case_name": result.matched_case_name,
        "matched_url": result.matched_url,
        "matched_court": result.matched_court,
        "matched_date": result.matched_date,
        "matched_description": result.matched_description,
        "diagnostics": result.diagnostics,
        "error": result.error,
    }


if _public_mode:
    # Public mode: Get & Print is the homepage; /get redirects to /.
    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve Get & Print as the homepage in public mode."""
        html_path = _static_dir / "get.html"
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    from fastapi.responses import RedirectResponse

    @app.get("/get")
    async def get_redirect():
        return RedirectResponse("/")
else:
    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the single-page frontend."""
        html_path = _static_dir / "index.html"
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/get", response_class=HTMLResponse)
    async def get_and_print():
        """Serve the Get and Print page."""
        html_path = _static_dir / "get.html"
        return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/health")
async def health():
    """Health check — reports token presence and cache size."""
    has_token = bool(os.environ.get("COURTLISTENER_API_TOKEN", ""))
    return {
        "status": "ok",
        "has_api_token": has_token,
        "cache_size": len(_cache),
    }


@app.post("/api/verify")
async def verify(request: Request):
    """Verify citations via SSE stream.

    Accepts JSON body: {"citations": ["cite1", "cite2", ...]}
    Streams SSE events: start, result, progress, done, error.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON body"}, status_code=400
        )

    citations = body.get("citations", [])
    if not isinstance(citations, list):
        return JSONResponse(
            {"error": "citations must be a list"}, status_code=400
        )

    # Filter empty strings
    citations = [c.strip() for c in citations if c.strip()]

    if not citations:
        return JSONResponse(
            {"error": "No citations provided"}, status_code=400
        )

    if len(citations) > MAX_CITATIONS:
        return JSONResponse(
            {"error": f"Maximum {MAX_CITATIONS} citations per request"},
            status_code=400,
        )

    token = _get_api_token(request)

    async def event_generator():
        yield {
            "event": "start",
            "data": json.dumps({"total": len(citations)}),
        }

        async with AsyncCourtListenerClient(api_token=token) as client:
            for i, citation_text in enumerate(citations):
                # Check cache first
                cached = _cache.get(citation_text)
                if cached is not None:
                    result_dict = _result_to_dict(cached)
                    result_dict["index"] = i
                    result_dict["cached"] = True
                    yield {
                        "event": "result",
                        "data": json.dumps(result_dict),
                    }
                else:
                    try:
                        result = await _verifier.verify_async(
                            client, citation_text
                        )
                        _cache.put(citation_text, result)
                        result_dict = _result_to_dict(result)
                        result_dict["index"] = i
                        result_dict["cached"] = False
                        yield {
                            "event": "result",
                            "data": json.dumps(result_dict),
                        }
                    except Exception as exc:
                        logger.exception(
                            "Error verifying citation: %s", citation_text
                        )
                        yield {
                            "event": "result",
                            "data": json.dumps({
                                "index": i,
                                "input_citation": citation_text,
                                "status": "ERROR",
                                "confidence": 0.0,
                                "matched_case_name": None,
                                "matched_url": None,
                                "diagnostics": [],
                                "error": str(exc),
                                "cached": False,
                            }),
                        }

                yield {
                    "event": "progress",
                    "data": json.dumps({
                        "completed": i + 1,
                        "total": len(citations),
                    }),
                }

        yield {"event": "done", "data": json.dumps({"total": len(citations)})}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# PDF download endpoints
# ---------------------------------------------------------------------------

def _sanitize_filename(name: str) -> str:
    """Turn a case name into a safe filename (ASCII, no special chars)."""
    # Replace common legal abbreviations
    name = name.replace("/", " v ")
    # Keep only alphanumeric, spaces, hyphens, periods
    name = re.sub(r"[^\w\s\-.]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    # Truncate
    if len(name) > 80:
        name = name[:80].rsplit(" ", 1)[0]
    return name or "document"


@app.post("/api/download-pdfs")
async def download_pdfs(request: Request):
    """Download PDFs for the given matched_urls, returned as a zip file.

    Accepts JSON body: {"urls": [{"matched_url": "...", "case_name": "..."}, ...]}
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    items = body.get("urls", [])
    if not isinstance(items, list) or not items:
        return JSONResponse({"error": "No URLs provided"}, status_code=400)

    if len(items) > 50:
        return JSONResponse(
            {"error": "Maximum 50 PDFs per download"}, status_code=400
        )

    # Phase 1: Resolve matched_urls to PDF download URLs (parallel, rate-limited)
    async def _resolve_one(
        client: AsyncCourtListenerClient, item: dict,
    ) -> dict[str, str | None]:
        matched_url = item.get("matched_url", "")
        case_name = item.get("case_name", "document")
        pdf_url = await client.get_pdf_url(matched_url)
        logger.info(
            "PDF resolve: %s -> %s",
            matched_url, pdf_url or "NO PDF URL",
        )
        return {"pdf_url": pdf_url, "case_name": case_name, "matched_url": matched_url}

    token = _get_api_token(request)

    async with AsyncCourtListenerClient(api_token=token) as client:
        resolved = await asyncio.gather(
            *[_resolve_one(client, item) for item in items]
        )

    # Phase 2: Download PDFs in parallel (storage.courtlistener.com, not CL API)
    download_sem = asyncio.Semaphore(5)
    ssl_ctx = _ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    async def _download_one(
        session: aiohttp.ClientSession, entry: dict,
    ) -> tuple[str, bytes | None]:
        """Return (case_name, pdf_bytes or None)."""
        case_name = entry["case_name"] or "document"
        pdf_url = entry["pdf_url"]
        if not pdf_url:
            return (case_name, None)
        async with download_sem:
            try:
                async with session.get(
                    pdf_url,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True,
                ) as resp:
                    if resp.status != 200:
                        logger.info("PDF download %s: HTTP %s", pdf_url, resp.status)
                        return (case_name, None)
                    content_type = resp.content_type or ""
                    if "html" in content_type:
                        logger.info("PDF download %s: got HTML instead of PDF", pdf_url)
                        return (case_name, None)
                    return (case_name, await resp.read())
            except Exception as exc:
                logger.info("PDF download %s: %s", pdf_url, exc)
                return (case_name, None)

    buf = io.BytesIO()
    downloaded = 0
    skipped_names: list[str] = []

    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(
            *[_download_one(session, entry) for entry in resolved]
        )

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_filenames: set[str] = set()
        for case_name, pdf_bytes in results:
            if pdf_bytes is None:
                skipped_names.append(case_name)
                continue
            base = _sanitize_filename(case_name)
            filename = f"{base}.pdf"
            counter = 2
            while filename in seen_filenames:
                filename = f"{base} ({counter}).pdf"
                counter += 1
            seen_filenames.add(filename)
            zf.writestr(filename, pdf_bytes)
            downloaded += 1

    if downloaded == 0:
        return JSONResponse(
            {"error": f"No PDFs available for the selected citations ({len(skipped_names)} skipped — opinions may be HTML-only, dockets may lack documents)"},
            status_code=404,
        )

    buf.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="citation_pdfs.zip"',
        "x-downloaded": str(downloaded),
        "x-skipped": str(len(skipped_names)),
        "Access-Control-Expose-Headers": "x-downloaded, x-skipped",
    }
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Text download endpoint
# ---------------------------------------------------------------------------

@app.post("/api/download-texts")
async def download_texts(request: Request):
    """Download opinion texts for the given matched_urls, returned as a zip of .txt files.

    Accepts JSON body: {"urls": [{"matched_url": "...", "case_name": "..."}, ...]}
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    items = body.get("urls", [])
    if not isinstance(items, list) or not items:
        return JSONResponse({"error": "No URLs provided"}, status_code=400)

    if len(items) > 50:
        return JSONResponse(
            {"error": "Maximum 50 texts per download"}, status_code=400
        )

    # Fetch opinion text + metadata for each URL (parallel)
    async def _fetch_one(
        client: AsyncCourtListenerClient, item: dict,
    ) -> dict[str, Any]:
        matched_url = item.get("matched_url", "")
        case_name = item.get("case_name", "document")
        result = await client.get_opinion_text_with_metadata(matched_url)
        logger.info(
            "Text resolve: %s -> %s chars",
            matched_url, len(result["text"]) if result else 0,
        )
        if result:
            # Prefer the caller's case_name if the API didn't return one
            if not result.get("case_name"):
                result["case_name"] = case_name
            result["matched_url"] = matched_url
        else:
            result = {"text": None, "case_name": case_name, "matched_url": matched_url}
        return result

    token = _get_api_token(request)

    async with AsyncCourtListenerClient(api_token=token) as client:
        fetched = await asyncio.gather(
            *[_fetch_one(client, item) for item in items]
        )

    # Assemble zip of .txt files
    buf = io.BytesIO()
    downloaded = 0
    skipped_names: list[str] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_filenames: set[str] = set()
        for entry in fetched:
            case_name = entry.get("case_name") or "document"
            text = entry.get("text")
            if not text:
                skipped_names.append(case_name)
                continue

            # Build file content with rich metadata header
            lines = []
            lines.append(case_name)
            citations = entry.get("citations", [])
            if citations:
                lines.append(", ".join(citations))
            court = entry.get("court", "")
            if court:
                lines.append(court)
            date_filed = entry.get("date_filed", "")
            if date_filed:
                lines.append(f"Filed: {date_filed}")
            docket_number = entry.get("docket_number", "")
            if docket_number:
                lines.append(f"Docket No. {docket_number}")
            lines.append(f"Source: {entry.get('matched_url', '')}")
            lines.append("-" * 60)
            lines.append("")
            header = "\n".join(lines) + "\n"
            content = header + text

            base = _sanitize_filename(case_name)
            filename = f"{base}.txt"
            counter = 2
            while filename in seen_filenames:
                filename = f"{base} ({counter}).txt"
                counter += 1
            seen_filenames.add(filename)
            zf.writestr(filename, content)
            downloaded += 1

    if downloaded == 0:
        return JSONResponse(
            {"error": f"No text available for the selected citations ({len(skipped_names)} skipped -- no text on CourtListener)"},
            status_code=404,
        )

    buf.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="citation_texts.zip"',
        "x-downloaded": str(downloaded),
        "x-skipped": str(len(skipped_names)),
        "Access-Control-Expose-Headers": "x-downloaded, x-skipped",
    }
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# QC review endpoints
# ---------------------------------------------------------------------------

@app.get("/qc", response_class=HTMLResponse)
async def qc_page():
    """Serve the QC review page."""
    html_path = _static_dir / "qc.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/qc/runs")
async def qc_runs():
    """List available JSON sidecar files from tests/data/results/."""
    if not _results_dir.exists():
        return []
    runs = []
    for p in sorted(_results_dir.glob("*.json"), reverse=True):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("_metadata", {})
            runs.append({
                "filename": p.name,
                "generated_at": meta.get("generated_at", ""),
                "sample_size": meta.get("sample_size", 0),
                "result_count": len(data.get("results", [])),
                "git_hash": meta.get("git_hash", ""),
                "seed": meta.get("seed", ""),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return runs


@app.get("/api/qc/run/{filename}")
async def qc_run(filename: str):
    """Load a sidecar file, enriched with CSV QC data and fuzzy duplicates."""
    # Sanitize filename — only allow simple filenames
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
    sidecar_path = _results_dir / filename
    if not sidecar_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)

    try:
        with open(sidecar_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    enriched_results = []
    for item in data.get("results", []):
        cite_text = item.get("citation_text", "")
        csv_row = _master_csv.get_row(cite_text)

        enriched = {
            **item,
            "qc_status": "",
            "qc_notes": "",
            "context": "",
            "pdf": item.get("pdf", ""),
            "case_name": "",
            "volume": "",
            "reporter": "",
            "page": "",
        }

        if csv_row:
            enriched["qc_status"] = csv_row.get("qc_status", "")
            enriched["qc_notes"] = csv_row.get("qc_notes", "")
            enriched["context"] = csv_row.get("context", "")
            enriched["pdf"] = csv_row.get("pdf", enriched["pdf"])
            enriched["case_name"] = csv_row.get("case_name", "")
            enriched["volume"] = csv_row.get("volume", "")
            enriched["reporter"] = csv_row.get("reporter", "")
            enriched["page"] = csv_row.get("page", "")

        # Find duplicates
        enriched["duplicates"] = _master_csv.find_duplicates(
            case_name=enriched.get("case_name") or item.get("matched_case_name"),
            volume=enriched.get("volume"),
            reporter=enriched.get("reporter"),
            page=enriched.get("page"),
            exclude_citation=cite_text,
        )

        enriched_results.append(enriched)

    return {
        "metadata": data.get("_metadata", {}),
        "results": enriched_results,
    }


@app.post("/api/qc/save")
async def qc_save(request: Request):
    """Save a QC decision back to the master CSV."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    citation_text = body.get("citation_text", "").strip()
    qc_status = body.get("qc_status", "").strip()
    qc_notes = body.get("qc_notes", "").strip()

    if not citation_text:
        return JSONResponse({"error": "citation_text required"}, status_code=400)

    valid_statuses = {"approved", "rerun", "duplicate", "ignore", "investigate", "data", ""}
    if qc_status not in valid_statuses:
        return JSONResponse(
            {"error": f"Invalid qc_status. Must be one of: {', '.join(sorted(valid_statuses))}"},
            status_code=400,
        )

    # Get the full row before updating (for context in TODO/contributions)
    csv_row = _master_csv.get_row(citation_text)

    ok = _master_csv.update_qc(citation_text, qc_status, qc_notes)
    if not ok:
        return JSONResponse(
            {"error": "Citation not found in master CSV"},
            status_code=404,
        )

    # Auto-append to QC_TRIAGE.md for "investigate" items
    if qc_status == "investigate" and csv_row:
        _append_to_todo(citation_text, qc_notes, csv_row)

    # Auto-append to flp_contributions.md for "data" items
    if qc_status == "data" and csv_row:
        _append_to_contributions(citation_text, qc_notes, csv_row)

    return {"ok": True, "citation_text": citation_text, "qc_status": qc_status}


_qc_triage_path = _project_root / "scratch" / "QC_TRIAGE.md"
_contributions_path = _project_root / "scratch" / "flp_contributions.md"


def _append_to_todo(citation_text: str, notes: str, row: dict) -> None:
    """Append an investigate item to QC_TRIAGE.md for later categorization."""
    try:
        content = _qc_triage_path.read_text(encoding="utf-8") if _qc_triage_path.exists() else ""

        # Don't add duplicates
        if citation_text in content:
            return

        pdf = row.get("pdf", "unknown")
        v_status = row.get("v_status", "")
        v_confidence = row.get("v_confidence", "")
        v_url = row.get("v_url", "")

        entry = f"\n**{citation_text}**\n"
        entry += f"Source: {pdf}. Verification: {v_status} ({v_confidence}). "
        if v_url:
            entry += f"Matched: {v_url}. "
        if notes:
            entry += f"Notes: {notes}. "
        entry += f"Added {__import__('datetime').date.today().isoformat()} from QC review.\n"

        content += entry

        _qc_triage_path.write_text(content, encoding="utf-8")
        logger.info("Added investigate item to QC_TRIAGE.md: %s", citation_text)
    except Exception:
        logger.exception("Failed to append to QC_TRIAGE.md")


def _append_to_contributions(citation_text: str, notes: str, row: dict) -> None:
    """Append a data quality item to scratch/flp_contributions.md section 6."""
    try:
        content = _contributions_path.read_text(encoding="utf-8") if _contributions_path.exists() else ""

        # Don't add duplicates
        if citation_text in content:
            return

        pdf = row.get("pdf", "unknown")
        v_status = row.get("v_status", "")

        entry = f"  - **{citation_text}** — "
        if notes:
            entry += f"{notes}. "
        entry += f"Source: {pdf}. Verification: {v_status}. "
        entry += "Added automatically from QC review.\n"

        # Insert before the "Action: Collect more examples" line
        action_marker = "- Action: Collect more examples before reporting."
        if action_marker in content:
            content = content.replace(
                action_marker,
                f"{entry}{action_marker}",
            )
        else:
            content += f"\n{entry}"

        _contributions_path.write_text(content, encoding="utf-8")
        logger.info("Added data item to flp_contributions.md: %s", citation_text)
    except Exception:
        logger.exception("Failed to append to flp_contributions.md")


@app.get("/api/qc/opinion-text")
async def qc_opinion_text(url: str):
    """Fetch the first ~2000 chars of opinion text from CourtListener API."""
    import re

    opinion_match = re.search(r"/opinion/(\d+)/", url)
    docket_match = re.search(r"/docket/(\d+)/(\d+)/", url)

    try:
        async with AsyncCourtListenerClient() as client:
            text = ""
            case_name = ""
            date_filed = ""
            court = ""

            if opinion_match:
                # Fetch opinion text via cluster -> sub_opinions
                cluster_id = opinion_match.group(1)
                cluster_url = f"{client.BASE_URL}/clusters/{cluster_id}/"
                cluster_data = await client._request_with_retry("GET", cluster_url)
                case_name = cluster_data.get("case_name", "")
                date_filed = cluster_data.get("date_filed", "")
                court = cluster_data.get("court", "")

                sub_opinions = cluster_data.get("sub_opinions", [])
                if sub_opinions:
                    opinion_url = sub_opinions[0]
                    if isinstance(opinion_url, str) and opinion_url.startswith("http"):
                        opinion_data = await client._request_with_retry("GET", opinion_url)
                    elif isinstance(opinion_url, dict):
                        opinion_data = opinion_url
                    else:
                        opinion_url = f"{client.BASE_URL}/opinions/{opinion_url}/"
                        opinion_data = await client._request_with_retry("GET", opinion_url)

                    text = opinion_data.get("plain_text", "")
                    if not text:
                        html = opinion_data.get("html_with_citations", "") or opinion_data.get("html", "")
                        if html:
                            text = re.sub(r"<[^>]+>", " ", html)
                            text = re.sub(r"\s+", " ", text).strip()

            elif docket_match:
                # Fetch docket entry document text
                docket_id = docket_match.group(1)
                entry_number = docket_match.group(2)
                entry_url = f"{client.BASE_URL}/docket-entries/"
                entry_data = await client._request_with_retry(
                    "GET", entry_url,
                    params={"docket": docket_id, "entry_number": entry_number},
                )
                results = entry_data.get("results", [])
                if results:
                    entry = results[0]
                    recap_docs = entry.get("recap_documents", [])
                    if recap_docs:
                        text = recap_docs[0].get("plain_text", "")
                    desc = entry.get("description", "")
                    if desc:
                        case_name = desc
                    date_filed = entry.get("date_filed", "")
            else:
                return JSONResponse({"error": "Could not parse opinion or docket ID from URL"}, status_code=400)

            # Truncate to first ~2000 chars at a sentence boundary
            if len(text) > 2000:
                cutoff = text.rfind(".", 0, 2000)
                if cutoff > 500:
                    text = text[:cutoff + 1] + "\n\n[...]"
                else:
                    text = text[:2000] + "\n\n[...]"

            return {
                "text": text,
                "case_name": case_name,
                "date_filed": date_filed,
                "court": court,
            }

    except Exception as exc:
        logger.exception("Error fetching opinion text for %s", url)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Batch verification from QC page
# ---------------------------------------------------------------------------

def _get_git_hash() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


_NEW_COLUMNS = [
    "v_status", "v_confidence", "v_url", "v_matched_name",
    "v_git_hash", "qc_status", "qc_notes",
]


def _is_actionable(row: dict) -> bool:
    if row.get("qc_status") == "rerun":
        return True
    if row.get("qc_status") in ("duplicate", "ignore", "investigate", "data"):
        return False
    if not row.get("v_status"):
        return True
    return False


def _parsed_citation_from_row(row: dict) -> ParsedCitation:
    def _int_or_none(val: str | None) -> int | None:
        if not val:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    case_name = row.get("case_name") or None
    plaintiff = row.get("plaintiff") or None
    defendant = row.get("defendant") or None
    if not case_name and plaintiff and defendant:
        case_name = f"{plaintiff} v. {defendant}"

    return ParsedCitation(
        raw_text=row.get("citation_text", ""),
        case_name=case_name,
        plaintiff=plaintiff,
        defendant=defendant,
        volume=row.get("volume") or None,
        reporter=row.get("reporter") or None,
        page=row.get("page") or None,
        court=row.get("court") or None,
        year=_int_or_none(row.get("year")),
        month=_int_or_none(row.get("month")),
        day=_int_or_none(row.get("day")),
        docket_number=row.get("docket_number") or None,
        is_westlaw=row.get("is_westlaw", "").upper() in ("TRUE", "1", "YES"),
        wl_number=row.get("wl_number") or None,
    )


@app.post("/api/qc/run-batch")
async def qc_run_batch(request: Request):
    """Run a new verification batch via SSE, writing results to CSV and JSON sidecar."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    sample_size = body.get("sample_size", 10)
    sample_size = max(1, min(sample_size, 100))
    rerun_only = body.get("rerun_only", False)
    batch_filter = body.get("filter", "all")

    # Read CSV
    csv_path = _default_csv
    if not csv_path.exists():
        return JSONResponse({"error": "Master CSV not found"}, status_code=404)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        all_rows = list(reader)

    for col in _NEW_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    # Filter actionable
    if rerun_only:
        actionable = [r for r in all_rows if r.get("qc_status") == "rerun"]
    else:
        actionable = [r for r in all_rows if _is_actionable(r)]

    # Apply batch filter
    if batch_filter == "unpublished":
        actionable = [r for r in actionable
                      if r.get("is_westlaw", "").upper() in ("TRUE", "1", "YES")]
    elif batch_filter == "post2020":
        def _year_ge(row: dict, threshold: int) -> bool:
            try:
                return int(row.get("year", "0")) >= threshold
            except (ValueError, TypeError):
                return False
        actionable = [r for r in actionable if _year_ge(r, 2021)]
    elif batch_filter == "hard":
        def _is_hard(row: dict) -> bool:
            is_wl = row.get("is_westlaw", "").upper() in ("TRUE", "1", "YES")
            try:
                is_recent = int(row.get("year", "0")) >= 2021
            except (ValueError, TypeError):
                is_recent = False
            return is_wl or is_recent
        actionable = [r for r in actionable if _is_hard(r)]

    if not actionable:
        return JSONResponse({"error": "No pending citations to verify"}, status_code=200)

    # Sample
    seed_val = random.randrange(10000)
    random.seed(seed_val)
    to_verify = random.sample(actionable, min(sample_size, len(actionable)))

    async def event_generator():
        yield {
            "event": "start",
            "data": json.dumps({
                "total": len(to_verify),
                "seed": seed_val,
                "actionable": len(actionable),
            }),
        }

        git_hash = _get_git_hash()
        results_for_sidecar: list[dict] = []
        t_start = time.monotonic()

        # Separate short cites from real citations
        batch_citations: list[str] = []
        batch_parsed: list[ParsedCitation] = []
        batch_row_indices: list[int] = []
        skipped: list[tuple[int, dict]] = []

        for seq, row in enumerate(to_verify):
            citation_text = row.get("citation_text", "").strip()
            case_name = row.get("case_name", "").strip()

            if not case_name or case_name == "v." or case_name.startswith("None v. None"):
                row["v_status"] = "SKIPPED"
                row["v_confidence"] = ""
                row["v_url"] = ""
                row["v_matched_name"] = ""
                row["v_git_hash"] = git_hash or ""
                if row.get("qc_status") == "rerun":
                    row["qc_status"] = ""
                    row["qc_notes"] = ""
                sidecar_entry = {
                    "citation_text": citation_text,
                    "classification": row.get("classification", ""),
                    "pdf": row.get("pdf", ""),
                    "status": "SKIPPED",
                    "confidence": 0.0,
                    "matched_case_name": None,
                    "matched_url": None,
                    "diagnostics": ["Short cite with no case name"],
                }
                results_for_sidecar.append(sidecar_entry)
                skipped.append((seq, row))
                yield {
                    "event": "result",
                    "data": json.dumps({
                        "index": seq,
                        "citation_text": citation_text,
                        "status": "SKIPPED",
                        "confidence": 0.0,
                    }),
                }
                continue

            batch_citations.append(citation_text)
            batch_parsed.append(_parsed_citation_from_row(row))
            batch_row_indices.append(seq)

        # Verify batch — run concurrently, stream results as they complete.
        # The async client's semaphore (MAX_CONCURRENT=5) and rate limiter
        # (MIN_REQUEST_INTERVAL=0.5s) keep CourtListener happy.
        if batch_citations:
            queue: asyncio.Queue = asyncio.Queue()

            async def _verify_one(
                idx: int, cite_text: str, parsed: ParsedCitation,
                client: AsyncCourtListenerClient,
            ) -> None:
                try:
                    result = await _verifier.verify_async(client, cite_text, parsed=parsed)
                    await queue.put(("ok", idx, cite_text, result, None))
                except Exception as exc:
                    logger.exception("Batch verify error: %s", cite_text)
                    await queue.put(("error", idx, cite_text, None, exc))

            async with AsyncCourtListenerClient() as client:
                # Launch all verifications as concurrent tasks
                tasks = [
                    asyncio.create_task(
                        _verify_one(i, cite_text, parsed, client)
                    )
                    for i, (cite_text, parsed) in enumerate(
                        zip(batch_citations, batch_parsed)
                    )
                ]

                # Stream results as they complete
                for completed_n in range(1, len(tasks) + 1):
                    status, i, cite_text, result, exc = await queue.get()
                    row = to_verify[batch_row_indices[i]]

                    if status == "ok":
                        row["v_status"] = result.status.value
                        row["v_confidence"] = str(result.confidence)
                        row["v_url"] = result.matched_url or ""
                        row["v_matched_name"] = result.matched_case_name or ""
                        row["v_git_hash"] = git_hash or ""
                        if row.get("qc_status") == "rerun":
                            row["qc_status"] = ""
                            row["qc_notes"] = ""

                        sidecar_entry = {
                            "citation_text": cite_text,
                            "classification": row.get("classification", ""),
                            "pdf": row.get("pdf", ""),
                            "status": result.status.value,
                            "confidence": result.confidence,
                            "matched_case_name": result.matched_case_name,
                            "matched_url": result.matched_url,
                            "matched_court": result.matched_court,
                            "matched_date": result.matched_date,
                            "matched_description": result.matched_description,
                            "diagnostics": result.diagnostics,
                        }
                        results_for_sidecar.append(sidecar_entry)

                        yield {
                            "event": "result",
                            "data": json.dumps({
                                "index": batch_row_indices[i],
                                "citation_text": cite_text,
                                "status": result.status.value,
                                "confidence": result.confidence,
                                "matched_case_name": result.matched_case_name,
                            }),
                        }
                    else:
                        yield {
                            "event": "result",
                            "data": json.dumps({
                                "index": batch_row_indices[i],
                                "citation_text": cite_text,
                                "status": "ERROR",
                                "error": str(exc),
                            }),
                        }

                    yield {
                        "event": "progress",
                        "data": json.dumps({
                            "completed": completed_n + len(skipped),
                            "total": len(to_verify),
                        }),
                    }

                # Ensure all tasks are done (they should be)
                await asyncio.gather(*tasks)

        # Write CSV back
        bak = csv_path.with_suffix(".csv.bak")
        shutil.copy2(csv_path, bak)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in all_rows:
                for col in _NEW_COLUMNS:
                    if col not in row:
                        row[col] = ""
                writer.writerow(row)

        # Force MasterCSV to reload
        _master_csv._rows = None

        # Write JSON sidecar
        _results_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d")
        sidecar_name = f"verification_{timestamp}_csv_seed{seed_val}.json"
        sidecar_path = _results_dir / sidecar_name
        elapsed = time.monotonic() - t_start

        by_status: dict[str, int] = {}
        for r in results_for_sidecar:
            s = r["status"]
            by_status[s] = by_status.get(s, 0) + 1

        sidecar_data = {
            "_metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "git_hash": git_hash,
                "seed": str(seed_val),
                "sample_size": len(to_verify),
                "source": str(csv_path),
                "elapsed_seconds": round(elapsed, 1),
            },
            "results": results_for_sidecar,
        }
        with open(sidecar_path, "w") as f:
            json.dump(sidecar_data, f, indent=2)

        yield {
            "event": "done",
            "data": json.dumps({
                "total": len(to_verify),
                "by_status": by_status,
                "sidecar": sidecar_name,
                "elapsed": round(elapsed, 1),
                "seed": seed_val,
            }),
        }

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
