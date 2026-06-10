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

import json
from typing import Any


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
