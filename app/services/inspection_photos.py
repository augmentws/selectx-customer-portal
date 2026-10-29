"""Fetch GoCanvas inspection photos into object storage.

A photo field's images come from GET /submissions/{id}/values/{value_id} as a zip
("Images_of_Pest_Activity.zip" holding "Images_of_Pest_Activity_26574236658_1.jpeg", ...).
Each image is a stored file (app.services.files) at
operators/{operator}/inspections/{submission}/{value_id}/{position}, for the company of the
submission's location (none until the submission is linked to one).

Like document files: each value commits on its own, a value's own problem is recorded in
`file_error` and retried on the next run, and GoCanvas or storage being unreachable stops the
run (GoCanvasUnavailableError, StorageError). Response bodies are never logged.
"""

import io
import logging
import mimetypes
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.gocanvas import GoCanvasAuthError, GoCanvasClient
from app.models import InspectionPhoto, InspectionPhotoValue, InspectionSubmission
from app.services.files import company_for_location, store_file
from app.services.inspections import sync_photo_values
from app.storage import ObjectStorage

log = logging.getLogger(__name__)

FILE_SOURCE = "gocanvas_photo"
# A zip with more entries than this is refused rather than unpacked.
MAX_PHOTOS_PER_VALUE = 100
POSITION_IN_NAME = re.compile(r"_(\d+)\.[A-Za-z0-9]+$")
# Leading bytes of the image formats GoCanvas may send.
SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
)


class GoCanvasUnavailableError(Exception):
    """GoCanvas refused the credentials, failed, or couldn't be reached: stop the run."""


class PhotoValueError(Exception):
    """This value's own problem; recorded on it and retried next run."""


@dataclass
class PhotoFetchCounts:
    values_fetched: int = 0
    values_failed: int = 0
    photos_stored: int = 0

    def __str__(self) -> str:
        return (
            f"{self.values_fetched} photo fields fetched ({self.photos_stored} photos), "
            f"{self.values_failed} failed"
        )


def pending_values(db: Session, submission: InspectionSubmission) -> list[InspectionPhotoValue]:
    return list(
        db.scalars(
            select(InspectionPhotoValue)
            .where(
                InspectionPhotoValue.submission_id == submission.id,
                InspectionPhotoValue.fetched_at.is_(None),
                InspectionPhotoValue.removed_at.is_(None),
            )
            .order_by(InspectionPhotoValue.entry_id)
        )
    )


def fetch_submission_photos(
    db: Session,
    client: GoCanvasClient,
    storage: ObjectStorage,
    submission: InspectionSubmission,
    counts: PhotoFetchCounts | None = None,
) -> PhotoFetchCounts:
    """Fetch and store the submission's photo values not fetched yet. Commits per value."""
    counts = counts or PhotoFetchCounts()
    for value in pending_values(db, submission):
        value.fetch_attempts += 1
        try:
            images = _download(client, submission.gocanvas_submission_id, value.gocanvas_value_id)
        except PhotoValueError as exc:
            value.file_error = str(exc)[:500]
            counts.values_failed += 1
            db.commit()
            continue
        value.photos.clear()
        db.flush()
        company_id = company_for_location(db, submission.location_id)
        for position, file_name, data, content_type in images:
            key = (
                f"operators/{submission.operator_id}/inspections/"
                f"{submission.gocanvas_submission_id}/{value.gocanvas_value_id}/{position}"
            )
            stored = store_file(
                db,
                storage,
                operator_id=submission.operator_id,
                company_id=company_id,
                source=FILE_SOURCE,
                key=key,
                data=data,
                content_type=content_type,
                original_name=file_name,
            )
            value.photos.append(
                InspectionPhoto(position=position, file_name=file_name[:300], file_id=stored.id)
            )
        value.fetched_at = datetime.now(UTC)
        value.file_error = None
        counts.values_fetched += 1
        counts.photos_stored += len(images)
        db.commit()
    return counts


def backfill_photo_values(db: Session, submission: InspectionSubmission) -> None:
    """Record photo values for a submission parsed before photos were tracked."""
    sync_photo_values(submission)
    db.flush()


def _download(
    client: GoCanvasClient, submission_id: int, value_id: int
) -> list[tuple[int, str, bytes, str]]:
    """The value's images as (position, file name, data, content type)."""
    try:
        response = client.get(f"/submissions/{submission_id}/values/{value_id}")
    except GoCanvasAuthError as exc:
        raise GoCanvasUnavailableError(str(exc)) from exc
    except requests.RequestException as exc:
        raise GoCanvasUnavailableError(f"Could not reach GoCanvas: {type(exc).__name__}") from exc
    if response.status_code in (401, 403, 429) or response.status_code >= 500:
        raise GoCanvasUnavailableError(f"GoCanvas returned {response.status_code}")
    if response.status_code != 200:
        raise PhotoValueError(f"GoCanvas returned {response.status_code}")
    max_bytes = get_settings().document_max_bytes
    data = response.content
    if len(data) > max_bytes:
        raise PhotoValueError(f"Larger than the {max_bytes:,}-byte limit")
    content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip()
    if content_type.startswith("image/"):
        # A single image rather than a zip: keep it as the field's only photo.
        return [(1, _file_name(response) or f"{value_id}", data, content_type)]
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise PhotoValueError(f"Expected a zip of images, got {content_type or 'no type'}")
    return _unzip(data, max_bytes)


def _unzip(data: bytes, max_bytes: int) -> list[tuple[int, str, bytes, str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = [e for e in archive.infolist() if not e.is_dir()]
        if len(entries) > MAX_PHOTOS_PER_VALUE:
            raise PhotoValueError(f"Zip holds {len(entries)} files; refusing to unpack")
        images: list[tuple[int, str, bytes, str]] = []
        used: set[int] = set()
        for index, entry in enumerate(entries, start=1):
            # Declared sizes can lie; read one byte past the limit to be sure.
            with archive.open(entry) as handle:
                content = handle.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise PhotoValueError(f"{entry.filename}: larger than the limit")
            match = POSITION_IN_NAME.search(entry.filename)
            position = int(match.group(1)) if match else index
            while position in used:
                position += 1
            used.add(position)
            images.append((position, entry.filename, content, _content_type(entry, content)))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as exc:
        raise PhotoValueError(f"Unreadable zip: {type(exc).__name__}") from exc
    return sorted(images)


def _content_type(entry: zipfile.ZipInfo, content: bytes) -> str:
    for signature, content_type in SIGNATURES:
        if content.startswith(signature):
            return content_type
    guessed, _ = mimetypes.guess_type(entry.filename)
    return guessed or "application/octet-stream"


def _file_name(response: requests.Response) -> str | None:
    match = re.search(r'filename="([^"]+)"', response.headers.get("Content-Disposition") or "")
    return match.group(1) if match else None
