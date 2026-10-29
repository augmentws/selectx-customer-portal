"""Serving stored objects safely: shared by every route that returns a file."""

import re
from urllib.parse import quote

from fastapi import HTTPException, Response, status

from app.storage import StorageError, StorageNotConfiguredError, get_storage

# Shown in the browser; anything else (HTML, SVG, ...) is a download, so a stored file can
# never run script on our origin.
INLINE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"}


def _disposition(kind: str, file_name: str | None, fallback: str) -> str:
    name = file_name or fallback
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or fallback
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def file_response(
    storage_key: str, content_type: str | None, file_name: str | None, fallback_name: str
) -> Response:
    """The object at `storage_key`. Images and PDFs are shown inline; other types download."""
    try:
        stored = get_storage().get(storage_key)
    except StorageNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    content_type = content_type or stored.content_type
    kind = "inline" if content_type in INLINE_TYPES else "attachment"
    headers = {
        "Content-Disposition": _disposition(kind, file_name, fallback_name),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-cache",
    }
    # Chrome's PDF viewer won't load in a sandboxed document (ERR_BLOCKED_BY_CLIENT). A PDF
    # is still pinned to application/pdf by nosniff and renders in the browser's own viewer.
    if content_type != "application/pdf":
        headers["Content-Security-Policy"] = "sandbox"
    return Response(
        stored.data,
        media_type=content_type if kind == "inline" else "application/octet-stream",
        headers=headers,
    )
