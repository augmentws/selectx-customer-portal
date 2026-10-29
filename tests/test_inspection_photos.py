"""GoCanvas inspection photos: photo fields recorded on parse, zips fetched into storage,
failures retried, revisions refetched, and the loader and backfill commands.

GoCanvas answers GET /submissions/{id}/values/{value_id} with a zip named after the field,
holding "<Field>_<value_id>_<n>.jpeg" (confirmed against the real API).
"""

import copy
import io
import json
import re
import zipfile

import pytest
import responses
from sqlalchemy import select

from app import fetch_inspection_photos, load_inspections
from app.db.session import SessionLocal
from app.models import (
    InspectionKind,
    InspectionPhotoValue,
    InspectionSubmission,
    StoredFile,
    Tenant,
)
from app.services.gocanvas_connection import get_gocanvas_client
from app.services.inspection_photos import GoCanvasUnavailableError, fetch_submission_photos
from app.services.inspections import import_form, store_submission
from tests.conftest import GOCANVAS_BASE, GOCANVAS_TOKEN_URL
from tests.test_inspections import FIXTURES, FORM, submission

SUBMISSION_ID = 268565507
PEST_VALUE = 26574236658  # Front of House, Images of Pest Activity
VALUE_URL = re.compile(re.escape(GOCANVAS_BASE) + r"/submissions/(\d+)/values/(\d+)$")
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def photo_zip(value_id: int, count: int = 1, field: str = "Images_of_Pest_Activity") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for n in range(1, count + 1):
            archive.writestr(f"{field}_{value_id}_{n}.jpeg", JPEG + bytes([n]))
    return buffer.getvalue()


@pytest.fixture
def gocanvas():
    """Mocked GoCanvas: token, and every photo value answering a one-image zip unless a test
    sets `rsps.values[value_id]` to (status, body) or a photo count."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.post(GOCANVAS_TOKEN_URL, json={"access_token": "gocanvas-token", "expires_in": 7200})
        rsps.values = {}

        def value(request):
            value_id = int(VALUE_URL.search(request.url).group(2))
            answer = rsps.values.get(value_id, 1)
            if isinstance(answer, tuple):
                return answer[0], {}, answer[1]
            headers = {"Content-Disposition": 'attachment; filename="photos.zip"'}
            return 200, {"Content-Type": "application/zip", **headers}, photo_zip(value_id, answer)

        rsps.add_callback(responses.GET, VALUE_URL, value)
        yield rsps


def value_calls(rsps) -> list[int]:
    return [
        int(VALUE_URL.search(c.request.url).group(2))
        for c in rsps.calls
        if "values" in c.request.url
    ]


def stored(db, payload=None) -> InspectionSubmission:
    import_form(db, _world_op(db), FORM, InspectionKind.risk)
    result = store_submission(db, _world_op(db), payload or submission("pdf_sample"))
    db.commit()
    return result.submission


def _world_op(db):
    return db.scalar(select(Tenant.id).where(Tenant.slug == "op-a"))


def fetch(db, sub, storage):
    client = get_gocanvas_client(db, db.get(Tenant, sub.operator_id))
    return fetch_submission_photos(db, client, storage, sub)


def test_photo_fields_with_images_are_recorded_on_parse(world):
    with SessionLocal() as db:
        sub = stored(db)
        values = {v.gocanvas_value_id: v for v in sub.photo_values}
        # 15 photo fields say "Binary data is not displayed"; the 21 holding [] have none.
        assert len(values) == 15
        pest = values[PEST_VALUE]
        assert (pest.zone_key, pest.category, pest.fetched_at) == ("front_of_house", "pest", None)
        assert {v.category for v in values.values()} == {"pest", "sanitation", "structural"}


def test_photos_are_unzipped_into_storage_once(world, gocanvas, storage):
    gocanvas.values[PEST_VALUE] = 3
    with SessionLocal() as db:
        sub = stored(db)
        counts = fetch(db, sub, storage)
        assert (counts.values_fetched, counts.values_failed, counts.photos_stored) == (15, 0, 17)
        value = db.scalar(
            select(InspectionPhotoValue).where(InspectionPhotoValue.gocanvas_value_id == PEST_VALUE)
        )
        assert [
            (p.position, p.file.content_type, p.file.size_bytes, p.file.source)
            for p in value.photos
        ] == [
            (1, "image/jpeg", 37, "gocanvas_photo"),
            (2, "image/jpeg", 37, "gocanvas_photo"),
            (3, "image/jpeg", 37, "gocanvas_photo"),
        ]
        key = value.photos[1].file.storage_key
        assert key == f"operators/{sub.operator_id}/inspections/{SUBMISSION_ID}/{PEST_VALUE}/2"
        assert storage.objects[key] == (JPEG + b"\x02", "image/jpeg")
        assert value.photos[0].file_name == f"Images_of_Pest_Activity_{PEST_VALUE}_1.jpeg"
        # The submission isn't linked to a location, so its files have no company yet.
        assert value.photos[0].file.company_id is None

        # Stored photos are never fetched again.
        calls = len(value_calls(gocanvas))
        assert fetch(db, sub, storage).values_fetched == 0
        assert len(value_calls(gocanvas)) == calls


def test_a_values_own_failure_is_recorded_and_retried(world, gocanvas, storage):
    gocanvas.values[PEST_VALUE] = (404, b'{"error": "not found"}')
    with SessionLocal() as db:
        sub = stored(db)
        counts = fetch(db, sub, storage)
        assert (counts.values_fetched, counts.values_failed) == (14, 1)
        value = db.scalar(
            select(InspectionPhotoValue).where(InspectionPhotoValue.gocanvas_value_id == PEST_VALUE)
        )
        assert (value.fetched_at, value.file_error, value.fetch_attempts) == (
            None,
            "GoCanvas returned 404",
            1,
        )

        del gocanvas.values[PEST_VALUE]
        assert fetch(db, sub, storage).values_fetched == 1
        db.refresh(value)
        assert (value.file_error, len(value.photos), value.fetch_attempts) == (None, 1, 2)


def test_bad_zips_are_recorded_not_stored(world, gocanvas, storage):
    gocanvas.values[PEST_VALUE] = (200, b"<html>not a zip</html>")
    with SessionLocal() as db:
        sub = stored(db)
        fetch(db, sub, storage)
        value = db.scalar(
            select(InspectionPhotoValue).where(InspectionPhotoValue.gocanvas_value_id == PEST_VALUE)
        )
        assert value.file_error.startswith("Expected a zip of images")
        assert value.photos == []


def test_gocanvas_outage_stops_the_run(world, gocanvas, storage):
    gocanvas.values[PEST_VALUE] = (503, b"")
    with SessionLocal() as db:
        sub = stored(db)
        with pytest.raises(GoCanvasUnavailableError, match="503"):
            fetch(db, sub, storage)


def test_revisions_refetch_and_dropped_photos_are_marked_removed(world, gocanvas, storage):
    original = submission("pdf_sample")
    revised = copy.deepcopy(original)
    revised.update(revision=True, revised_at="2026-10-30T12:00:00Z")
    for response in revised["responses"]:
        if response["id"] == PEST_VALUE:
            response["value"] = []  # the revision removed the pest photos
    with SessionLocal() as db:
        sub = stored(db, original)
        fetch(db, sub, storage)
        sub = stored(db, revised)
        values = {v.gocanvas_value_id: v for v in sub.photo_values}
        assert values[PEST_VALUE].removed_at is not None
        assert len(values[PEST_VALUE].photos) == 1  # kept, never deleted
        others = [v for k, v in values.items() if k != PEST_VALUE]
        assert all(v.fetched_at is None for v in others)
        assert fetch(db, sub, storage).values_fetched == 14


def test_loader_fetches_photos_and_backfill_fills_in_older_loads(
    world, gocanvas, storage, tmp_path
):
    form_file = tmp_path / "form.json"
    form_file.write_text(json.dumps(FORM))
    files = [str(FIXTURES / f"submission_{n}.json") for n in ("pdf_sample", "ramp_digit")]
    args = ["--operator-id", str(world.op_a), "--form", str(form_file), "--kind", "risk"]

    assert load_inspections.main([*args, "--no-photos", files[1]]) == 0
    assert value_calls(gocanvas) == []
    assert load_inspections.main([*args, files[0]]) == 0
    with SessionLocal() as db:
        fetched = db.scalars(
            select(InspectionPhotoValue).where(InspectionPhotoValue.fetched_at.is_not(None))
        ).all()
        assert {v.submission.gocanvas_submission_id for v in fetched} == {SUBMISSION_ID}

    # The backfill fetches the submission loaded without photos, and nothing twice.
    before = len(value_calls(gocanvas))
    assert fetch_inspection_photos.main(["--operator-id", str(world.op_a)]) == 0
    with SessionLocal() as db:
        pending = db.scalars(
            select(InspectionPhotoValue).where(InspectionPhotoValue.fetched_at.is_(None))
        ).all()
        assert pending == []
        total = db.scalar(
            select(InspectionSubmission).where(
                InspectionSubmission.gocanvas_submission_id == submission("ramp_digit")["id"]
            )
        )
        assert len(value_calls(gocanvas)) - before == len(total.photo_values)


def test_commands_need_verified_gocanvas_access(world, storage, caplog):
    caplog.set_level("ERROR")
    assert fetch_inspection_photos.main(["--operator-id", str(world.op_b)]) == 1
    assert "verify GoCanvas API access" in caplog.text


def test_photo_files_follow_the_submissions_company(world, gocanvas, storage):
    unlinked = submission("pdf_sample")
    linked = copy.deepcopy(unlinked)
    linked["revised_at"] = "2026-10-30T12:00:00Z"
    for response in linked["responses"]:
        if response["export_label"] == "StoreNumbe":
            response["value"] = "Chipotle - Store #1"  # the world's "ACME TACOS - STORE #1"
    with SessionLocal() as db:
        sub = stored(db, unlinked)
        fetch(db, sub, storage)
        file_companies = (
            select(StoredFile.company_id)
            .where(
                StoredFile.source == "gocanvas_photo", StoredFile.storage_key.like("operators/%")
            )
            .distinct()
        )
        assert db.scalars(file_companies).all() == [None]

        # Linking the submission to a location moves its stored photos to that company,
        # without fetching them again unless the payload changed (it did: refetched too).
        sub = stored(db, linked)
        assert sub.location_id == world.location_a
        assert db.scalars(file_companies).all() == [world.company_a]
        fetch(db, sub, storage)
        assert db.scalars(file_companies).all() == [world.company_a]
