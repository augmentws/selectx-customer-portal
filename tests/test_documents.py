import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Document
from app.storage import StorageNotConfiguredError
from tests.conftest import headers_for, pestpac_document, pestpac_order
from tests.test_notes import STORE, _store_id
from tests.test_service_orders import _latest_job, _run_worker, _sync

PHOTO = b"\xff\xd8\xff\xe0 jpeg bytes"
PDF = b"%PDF-1.7 contract"


@pytest.fixture
def settings_env(monkeypatch):
    def use(**values: str):
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    yield use
    monkeypatch.undo()
    get_settings.cache_clear()


def _documents(client, onboarded):
    resp = client.get(
        f"/v1/locations/{_store_id(client, onboarded)}/documents", headers=onboarded["headers"]
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _admin(client, world):
    return headers_for(client, world.emails["admin_a"])


def _download_calls(pestpac) -> int:
    return sum("/download" in c.request.url for c in pestpac.calls)


def _sync_locations(client, onboarded):
    """The bill-to's manual "Sync location" job, run to completion (with any order sync queued
    before it)."""
    resp = client.post(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/locations/sync", headers=onboarded["headers"]
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["kind"] == "bill_to_location_sync"
    _run_worker()
    return _latest_job(client, onboarded)


def _photo_and_contract(pestpac):
    pestpac.documents_by_location[STORE] = [
        pestpac_document(2314160),
        pestpac_document(
            2272640,
            name="Contract - Ramp Unsigned",
            date="2026-08-17T00:00:00",
            file_name="Chipotle_Store_2254_RAMP2_Proposal.pdf",
        ),
    ]
    pestpac.document_files[2314160] = (200, "image/jpeg", PHOTO)
    pestpac.document_files[2272640] = (200, "application/pdf", PDF)


def test_documents_and_files_are_stored(client, world, onboarded, pestpac, storage):
    _photo_and_contract(pestpac)
    _sync_locations(client, onboarded)

    job = _latest_job(client, onboarded)
    assert job["status"] == "succeeded"
    assert job["progress"]["documents"]["added"] == 2
    assert job["progress"]["documents"]["files_stored"] == 2

    [listing] = [
        c.request.url for c in pestpac.calls if f"/Locations/{STORE}/documents" in c.request.url
    ]
    assert parse_qs(urlparse(listing).query) == {
        "startDate": ["2025-09-25"],
        "includeConditionDocuments": ["true"],
    }
    downloads = [c.request.url for c in pestpac.calls if "/download" in c.request.url]
    assert all(parse_qs(urlparse(u).query) == {"type": ["LocationDocument"]} for u in downloads)

    docs = _documents(client, onboarded)
    assert [d["pestpac_document_id"] for d in docs] == [2314160, 2272640]  # newest first
    photo = docs[0]
    assert photo["has_file"] and photo["content_type"] == "image/jpeg"
    assert photo["size_bytes"] == len(PHOTO)
    assert photo["include_on"] == {"service_orders": False, "portal": False, "mobile_app": True}
    [key] = [k for k in storage.objects if k.endswith("/documents/LocationDocument/2314160")]
    assert storage.objects[key] == (PHOTO, "image/jpeg")
    with SessionLocal() as db:
        stored = db.scalar(select(Document).where(Document.pestpac_document_id == 2314160))
        assert (stored.storage_key, stored.file.sha256, stored.file.source) == (
            key,
            hashlib.sha256(PHOTO).hexdigest(),
            "pestpac_document",
        )
        # The file belongs to the location's company, so GET /v1/files/{id} checks it there.
        assert str(stored.file.company_id) == str(world.company_a)

    resp = client.get(f"/v1/documents/{photo['id']}/file", headers=onboarded["headers"])
    assert resp.status_code == 200
    assert resp.content == PHOTO
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["content-disposition"].startswith("inline;")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-security-policy"] == "sandbox"


def test_pdfs_open_in_the_browser_viewer(client, world):
    # Chrome refuses to show a PDF in a sandboxed document, so PDFs aren't sandboxed.
    resp = client.get(f"/v1/documents/{world.document_a}/file", headers=_admin(client, world))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"].startswith("inline;")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in resp.headers


def test_files_are_fetched_once_but_metadata_refreshes(client, onboarded, pestpac):
    _photo_and_contract(pestpac)
    _sync_locations(client, onboarded)
    calls = _download_calls(pestpac)

    pestpac.documents_by_location[STORE][0]["Name"] = "DML Line (renamed)"
    job = _sync_locations(client, onboarded)
    assert _download_calls(pestpac) == calls
    assert job["progress"]["documents"]["updated"] == 2
    assert _documents(client, onboarded)[0]["name"] == "DML Line (renamed)"


def test_a_failed_file_is_recorded_and_retried(client, onboarded, pestpac):
    _photo_and_contract(pestpac)
    pestpac.document_files[2314160] = (500, "application/json", b"{}")
    _sync_locations(client, onboarded)

    job = _latest_job(client, onboarded)
    assert job["status"] == "succeeded"  # a file's problem doesn't fail the location
    assert job["progress"]["documents"]["files_failed"] == 1
    photo, contract = _documents(client, onboarded)
    assert not photo["has_file"] and photo["file_error"] == "PestPac download returned 500"
    assert contract["has_file"]

    pestpac.document_files[2314160] = (200, "image/jpeg", PHOTO)
    _sync_locations(client, onboarded)
    photo = _documents(client, onboarded)[0]
    assert photo["has_file"] and photo["file_error"] is None


# PestPac's API gateway answer for a file over its 10 MB limit (confirmed against PestPac).
TOO_BIG = (
    b'{"fault":{"faultstring":"Body buffer overflow",'
    b'"detail":{"errorcode":"protocol.http.TooBigBody"}}}'
)


def test_a_file_too_big_for_pestpac_fails_once_and_isnt_tried_again(client, onboarded, pestpac):
    _photo_and_contract(pestpac)
    pestpac.document_files[2314160] = (502, "application/json", TOO_BIG)
    job = _sync_locations(client, onboarded)
    assert job["progress"]["documents"]["files_failed"] == 1
    photo = _documents(client, onboarded)[0]
    assert not photo["has_file"] and photo["file_unavailable"]
    assert "over its 10 MB limit" in photo["file_error"]

    calls = _download_calls(pestpac)
    job = _sync_locations(client, onboarded)
    assert _download_calls(pestpac) == calls  # not downloaded again
    assert job["progress"]["documents"]["files_failed"] == 0
    assert _documents(client, onboarded)[0]["file_unavailable"]  # the record stays


def test_other_gateway_errors_are_retried(client, onboarded, pestpac):
    _photo_and_contract(pestpac)
    pestpac.document_files[2314160] = (502, "text/html", b"<html>Bad gateway</html>")
    _sync_locations(client, onboarded)
    photo = _documents(client, onboarded)[0]
    assert photo["file_error"] == "PestPac download returned 502"
    assert not photo["file_unavailable"]


def test_json_instead_of_a_file_is_not_stored(client, onboarded, pestpac, storage):
    pestpac.documents_by_location[STORE] = [pestpac_document(1)]
    pestpac.document_files[1] = (200, "application/json; charset=utf-8", b'{"Message": "x"}')
    _sync_locations(client, onboarded)
    [doc] = _documents(client, onboarded)
    assert doc["file_error"] == "PestPac sent JSON instead of the file"
    assert not [k for k in storage.objects if "/documents/" in k]  # nothing stored for it


def test_too_large_files_are_skipped_and_not_downloaded_again(
    client, onboarded, pestpac, settings_env
):
    settings_env(DOCUMENT_MAX_BYTES="10")
    _photo_and_contract(pestpac)
    _sync_locations(client, onboarded)
    assert _latest_job(client, onboarded)["progress"]["documents"]["files_too_large"] == 2
    calls = _download_calls(pestpac)

    _sync_locations(client, onboarded)
    assert _download_calls(pestpac) == calls
    photo = _documents(client, onboarded)[0]
    assert not photo["has_file"] and photo["size_bytes"] == len(PHOTO)
    assert photo["file_error"] == "Larger than the 10-byte limit"


def test_unknown_content_type_is_guessed_from_the_file_name(client, onboarded, pestpac):
    pestpac.documents_by_location[STORE] = [pestpac_document(1, file_name="report.pdf")]
    pestpac.document_files[1] = (200, "application/octet-stream", PDF)
    _sync_locations(client, onboarded)
    assert _documents(client, onboarded)[0]["content_type"] == "application/pdf"


def test_unsafe_types_download_instead_of_rendering(client, onboarded, pestpac):
    pestpac.documents_by_location[STORE] = [pestpac_document(1, file_name="page.html")]
    pestpac.document_files[1] = (200, "text/html", b"<script>alert(1)</script>")
    _sync_locations(client, onboarded)
    [doc] = _documents(client, onboarded)
    resp = client.get(f"/v1/documents/{doc['id']}/file", headers=onboarded["headers"])
    assert resp.headers["content-type"] == "application/octet-stream"
    assert resp.headers["content-disposition"].startswith("attachment;")


def test_same_id_in_two_types_is_two_documents(client, onboarded, pestpac):
    pestpac.documents_by_location[STORE] = [
        pestpac_document(7, document_type="LocationDocument"),
        pestpac_document(7, document_type="ConditionDocument"),
    ]
    _sync_locations(client, onboarded)
    types = sorted(d["document_type"] for d in _documents(client, onboarded))
    assert types == ["ConditionDocument", "LocationDocument"]


def test_unlisted_documents_are_marked_removed(client, onboarded, pestpac):
    pestpac.documents_by_location[STORE] = [
        pestpac_document(1, date="2026-10-01T00:00:00"),
        pestpac_document(2, date="2026-10-02T00:00:00"),
    ]
    _sync_locations(client, onboarded)
    pestpac.documents_by_location[STORE] = [pestpac_document(2, date="2026-10-02T00:00:00")]
    job = _sync_locations(client, onboarded)
    assert job["progress"]["documents"]["removed"] == 1
    assert [d["pestpac_document_id"] for d in _documents(client, onboarded)] == [2]


def test_documents_link_to_our_orders(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [pestpac_order(1863232, STORE, 180020)]
    pestpac.documents_by_location[STORE] = [pestpac_document(1, order_id=1863232)]
    _run_worker()  # the onboarding order sync
    _sync_locations(client, onboarded)
    [doc] = _documents(client, onboarded)
    assert doc["pestpac_order_id"] == 1863232 and doc["service_order_id"] is not None


def test_listing_failure_marks_the_job_partial(client, onboarded, pestpac):
    pestpac.documents_by_location[STORE] = 500
    job = _sync_locations(client, onboarded)
    assert job["status"] == "partial"
    assert job["error"] == "1 location(s) failed"
    [failure] = job["progress"]["failed_locations"]
    assert failure["pestpac_location_id"] == STORE
    assert job["progress"]["locations_done"] == 3  # the other locations still ran


def test_order_syncs_leave_documents_alone(client, onboarded, pestpac):
    _photo_and_contract(pestpac)
    job = _sync(client, onboarded)
    assert job["kind"] == "bill_to_service_orders" and job["status"] == "succeeded"
    assert not any("/documents" in c.request.url for c in pestpac.calls)
    assert _documents(client, onboarded) == []


def test_location_documents_sync(client, onboarded, pestpac):
    _photo_and_contract(pestpac)
    resp = client.post(
        f"/v1/locations/{_store_id(client, onboarded)}/sync",
        headers=onboarded["headers"],
    )
    assert resp.status_code == 202 and resp.json()["kind"] == "location_sync"
    _run_worker()
    job = _latest_job(client, onboarded)
    assert job["kind"] == "location_sync" and job["progress"]["locations_total"] == 1
    assert len(_documents(client, onboarded)) == 2


def test_without_storage_metadata_still_syncs(client, onboarded, pestpac, monkeypatch):
    def not_configured():
        raise StorageNotConfiguredError("Object storage is not configured (S3_BUCKET)")

    monkeypatch.setattr("app.services.sync_jobs.get_storage", not_configured)
    _photo_and_contract(pestpac)
    _sync_locations(client, onboarded)
    job = _latest_job(client, onboarded)
    assert job["status"] == "succeeded"
    assert job["progress"]["document_files"] == "Object storage is not configured (S3_BUCKET)"
    assert _download_calls(pestpac) == 0
    assert [d["has_file"] for d in _documents(client, onboarded)] == [False, False]


def test_file_not_stored_yet_is_404(client, onboarded, pestpac, monkeypatch):
    def not_configured():
        raise StorageNotConfiguredError("Object storage is not configured (S3_BUCKET)")

    monkeypatch.setattr("app.services.sync_jobs.get_storage", not_configured)
    pestpac.documents_by_location[STORE] = [pestpac_document(1)]
    _sync_locations(client, onboarded)
    [doc] = _documents(client, onboarded)
    resp = client.get(f"/v1/documents/{doc['id']}/file", headers=onboarded["headers"])
    assert resp.status_code == 404 and resp.json()["detail"] == "File not stored yet"


@pytest.mark.parametrize(
    ("garbled", "repaired"),
    [
        ("Filbert â€” Service Report.pdf", "Filbert — Service Report.pdf"),
        ("CafÃ© menu.pdf", "Café menu.pdf"),
        ("He said â€œhiâ€\x9d.pdf", "He said “hi”.pdf"),  # 0x9D: undefined in Windows-1252
        ("Crème brûlée.pdf", "Crème brûlée.pdf"),  # real accents: left alone
        ("Price €5 – ok", "Price €5 – ok"),
        ("日本語 â€” mixed", "日本語 â€” mixed"),  # can't be undone safely: left alone
    ],
)
def test_repair_mojibake(garbled, repaired):
    from app.schemas.pestpac import repair_mojibake

    assert repair_mojibake(garbled) == repaired


def test_names_garbled_in_pestpac_are_stored_repaired(client, onboarded, pestpac):
    """PestPac holds some names as UTF-8 read as Windows-1252 ("â€”" for "—"), sent correctly
    encoded, so they're repaired on the way in; a later sync fixes ones stored before."""
    pestpac.documents_by_location[STORE] = [
        pestpac_document(1, name="Report â€” Night 1", file_name="Filbert â€” Service 17.pdf")
    ]
    _sync_locations(client, onboarded)
    [doc] = _documents(client, onboarded)
    assert doc["name"] == "Report — Night 1"
    assert doc["file_name"] == "Filbert — Service 17.pdf"
