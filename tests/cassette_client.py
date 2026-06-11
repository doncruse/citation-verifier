"""Record/replay wrapper around CourtListenerClient.

The verifier reaches CourtListener through a handful of public client
methods, each returning JSON-serializable lists/dicts. This wrapper caches
those calls keyed by (method, args, kwargs):

- ``mode="record"`` calls the real client and stores every return value.
- ``mode="replay"`` returns the stored value and never touches the network.

Because every change we make to the verifier this session is *interpretation*
of the same API responses (scoring, gating), a recorded cassette lets the
whole big-corpus regression run offline, instantly, and deterministically.
Re-record periodically to pick up CourtListener data drift.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any


def load_cassette(path: str | Path) -> Any:
    """Load a cassette (or any JSON file) from ``path``.

    A ``.gz`` path is read with gzip; any other path is read as plain
    JSON. For transition robustness, a missing ``.gz`` path falls back to
    its plain ``.json`` sibling when one exists (so a machine that still
    has only the pre-migration plain cassette keeps working).
    """
    path = Path(path)
    if path.suffix == ".gz":
        if not path.exists():
            sibling = path.with_suffix("")  # strip ".gz" -> "..._cassette.json"
            if sibling.exists():
                return json.loads(sibling.read_text(encoding="utf-8"))
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))


def dump_cassette(path: str | Path, cassette: Any) -> None:
    """Atomically write ``cassette`` as JSON to ``path``.

    Gzip-compresses when ``path`` ends in ``.gz`` (cassettes), writes
    plain JSON otherwise (baselines). The temp-file + rename keeps a
    crash mid-write from corrupting the previous file.
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(cassette, indent=0)
    if path.suffix == ".gz":
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            f.write(text)
    else:
        tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# Public client methods whose return values are cached. Everything else
# (attributes, private helpers) passes straight through to the real client.
_CACHED_METHODS = frozenset({
    "citation_lookup",
    "search_opinions",
    "search_recap",
    "get_docket_entries",
    "get_cluster",
    "get_docket",
    "get_recap_document_metadata",
    "get_opinion_text",
    "get_opinion_text_with_metadata",
})


class CassetteMiss(KeyError):
    """Raised in replay mode when a call has no recorded entry."""


def _key(name: str, args: tuple, kwargs: dict) -> str:
    """Stable string key for a method call."""
    return json.dumps(
        [name, list(args), sorted(kwargs.items())],
        default=str,
        sort_keys=True,
    )


class CassetteClient:
    def __init__(self, real_client: Any, cassette: dict[str, Any], mode: str):
        # Assign internals first so __getattr__ never recurses on them.
        object.__setattr__(self, "_real", real_client)
        object.__setattr__(self, "_cassette", cassette)
        object.__setattr__(self, "_mode", mode)
        object.__setattr__(self, "misses", [])

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._real, name)
        if name not in _CACHED_METHODS or not callable(attr):
            return attr

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _key(name, args, kwargs)
            if self._mode == "replay":
                if key not in self._cassette:
                    self.misses.append(key)
                    raise CassetteMiss(key)
                return self._cassette[key]
            value = attr(*args, **kwargs)
            self._cassette[key] = value
            return value

        return wrapper
