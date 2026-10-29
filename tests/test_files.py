"""Stored files: GET /v1/files/{id} checks `files:read` against the file's company.

Who may open which file is in tests/test_access_matrix.py; these tests cover a company-scoped
grant (no system role has one yet) and the headers a file is served with.
"""

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Company, CompanyMembership, Permission, Role, StoredFile
from app.security.permissions import Perm, RoleScope
from app.services.auth import create_user
from tests.conftest import PASSWORD, headers_for


def _file(db, storage, operator_id, company_id, key):
    stored = StoredFile(
        operator_id=operator_id,
        company_id=company_id,
        source="gocanvas_photo",
        storage_key=key,
        content_type="image/jpeg",
        size_bytes=4,
        sha256="0" * 64,
    )
    db.add(stored)
    storage.put(key, b"\xff\xd8\xff\xe0", "image/jpeg")
    db.flush()
    return stored.id


def test_files_are_served_inline_and_sandboxed(client, world):
    admin_a = headers_for(client, world.emails["admin_a"])
    resp = client.get(f"/v1/files/{world.file_a}", headers=admin_a)
    assert resp.status_code == 200
    assert resp.content == b"\xff\xd8\xff\xe0"
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["content-disposition"].startswith(
        'inline; filename="Images_of_Pest_Activity_1_1.jpeg"'
    )
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-security-policy"] == "sandbox"


def test_a_company_grant_opens_only_its_own_companys_files(client, world, storage):
    with SessionLocal() as db:
        # A company-scoped role holding files:read (custom roles aren't offered in the app yet).
        role = Role(
            tenant_id=world.op_a,
            name="file_viewer",
            description="Opens its company's files",
            scope=RoleScope.company,
        )
        role.permissions = list(
            db.scalars(select(Permission).where(Permission.code == Perm.files_read.value))
        )
        db.add(role)
        user = create_user(db, email="viewer@test.example", password=PASSWORD)
        db.flush()
        db.add(CompanyMembership(user_id=user.id, company_id=world.company_a, role_id=role.id))
        other_company = Company(operator_id=world.op_a, name="Other Restaurants")
        db.add(other_company)
        db.flush()
        same_operator_other_company = _file(
            db, storage, world.op_a, other_company.id, "test/files/other"
        )
        no_company_yet = _file(db, storage, world.op_a, None, "test/files/unlinked")
        other_operator = _file(db, storage, world.op_b, world.company_b, "test/files/op-b")
        db.commit()

    viewer = headers_for(client, "viewer@test.example")
    assert client.get(f"/v1/files/{world.file_a}", headers=viewer).status_code == 200
    for file_id in (same_operator_other_company, no_company_yet, other_operator):
        assert client.get(f"/v1/files/{file_id}", headers=viewer).status_code == 404

    # An operator grant covers every company of the operator, and files with no company yet.
    staff_a = headers_for(client, world.emails["staff_a"])
    for file_id in (same_operator_other_company, no_company_yet):
        assert client.get(f"/v1/files/{file_id}", headers=staff_a).status_code == 200
    assert client.get(f"/v1/files/{other_operator}", headers=staff_a).status_code == 404


def test_unknown_file_is_404(client, world):
    admin_a = headers_for(client, world.emails["admin_a"])
    resp = client.get("/v1/files/00000000-0000-0000-0000-000000000000", headers=admin_a)
    assert resp.status_code == 404
