"""The embedding pin as a guardrail, not a README rule (section 4.4).

The indexer writes `embed_model` and `dimension` into the collection metadata. The API
compares that with its own EMBED_MODEL; on a mismatch /readyz returns 503 and logs the
conflict, so the pod sits at 0/1 READY instead of serving nonsense retrievals.
"""

from __future__ import annotations

from collections.abc import Mapping


def pin_mismatch(collection_metadata: Mapping[str, object], embed_model: str) -> str | None:
    """Return a message naming the conflict, or None when the pin holds."""
    built_with = collection_metadata.get("embed_model")
    if built_with is None:
        return (f"embedding model mismatch: the index records no embed_model, "
                f"cannot confirm it matches EMBED_MODEL={embed_model!r}")
    if str(built_with) != embed_model:
        return (f"embedding model mismatch: the index was built with {built_with!r} "
                f"(dimension {collection_metadata.get('dimension')}) but this API has "
                f"EMBED_MODEL={embed_model!r}; re-index or restore the ConfigMap")
    return None
