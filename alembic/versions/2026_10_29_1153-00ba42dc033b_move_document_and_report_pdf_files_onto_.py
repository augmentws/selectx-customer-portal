"""move document and report pdf files onto stored_files

Revision ID: 00ba42dc033b
Revises: 195de243a815
Create Date: 2026-10-29 11:53:00

Every stored PestPac document file and service report PDF gets a stored_files row (same
storage key, so nothing moves in object storage), and the documents and reports point at it.
Their own key, type, and hash columns are dropped; documents keep size_bytes, which also
records the size of files too large to store. Downgrade copies the columns back.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "00ba42dc033b"
down_revision: str | Sequence[str] | None = "195de243a815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("file_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_documents_file_id"), "documents", ["file_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_documents_file_id_stored_files"),
        "documents",
        "stored_files",
        ["file_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("reports", sa.Column("pdf_file_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_reports_pdf_file_id"), "reports", ["pdf_file_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_reports_pdf_file_id_stored_files"),
        "reports",
        "stored_files",
        ["pdf_file_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # A document's company is its location's bill-to's (none without a location).
    op.execute(
        """
        INSERT INTO stored_files (id, operator_id, company_id, source, storage_key,
            content_type, size_bytes, sha256, original_name, created_at, updated_at)
        SELECT gen_random_uuid(), d.operator_id, b.company_id, 'pestpac_document',
            d.storage_key, left(coalesce(d.content_type, 'application/octet-stream'), 100),
            coalesce(d.size_bytes, 0), coalesce(d.sha256, ''), left(d.file_name, 300),
            coalesce(d.file_stored_at, now()), now()
        FROM documents d
        LEFT JOIN locations l ON l.id = d.location_id
        LEFT JOIN bill_tos b ON b.id = l.bill_to_id
        WHERE d.storage_key IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE documents d SET file_id = f.id
        FROM stored_files f WHERE f.storage_key = d.storage_key
        """
    )
    op.execute(
        """
        INSERT INTO stored_files (id, operator_id, company_id, source, storage_key,
            content_type, size_bytes, sha256, original_name, created_at, updated_at)
        SELECT gen_random_uuid(), r.operator_id, r.company_id, 'report_pdf',
            r.pdf_storage_key, 'application/pdf', coalesce(r.pdf_size_bytes, 0),
            coalesce(r.pdf_sha256, ''), NULL, coalesce(r.finalized_at, now()), now()
        FROM reports r
        WHERE r.pdf_storage_key IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE reports r SET pdf_file_id = f.id
        FROM stored_files f WHERE f.storage_key = r.pdf_storage_key
        """
    )

    op.drop_column("documents", "storage_key")
    op.drop_column("documents", "content_type")
    op.drop_column("documents", "sha256")
    op.drop_column("documents", "file_stored_at")
    op.drop_column("reports", "pdf_storage_key")
    op.drop_column("reports", "pdf_size_bytes")
    op.drop_column("reports", "pdf_sha256")


def downgrade() -> None:
    op.add_column("documents", sa.Column("storage_key", sa.String(length=500), nullable=True))
    op.add_column("documents", sa.Column("content_type", sa.String(length=200), nullable=True))
    op.add_column("documents", sa.Column("sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "documents", sa.Column("file_stored_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("reports", sa.Column("pdf_storage_key", sa.String(length=500), nullable=True))
    op.add_column("reports", sa.Column("pdf_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("reports", sa.Column("pdf_sha256", sa.String(length=64), nullable=True))

    op.execute(
        """
        UPDATE documents d SET storage_key = f.storage_key, content_type = f.content_type,
            sha256 = nullif(f.sha256, ''), file_stored_at = f.created_at
        FROM stored_files f WHERE f.id = d.file_id
        """
    )
    op.execute(
        """
        UPDATE reports r SET pdf_storage_key = f.storage_key, pdf_size_bytes = f.size_bytes,
            pdf_sha256 = nullif(f.sha256, '')
        FROM stored_files f WHERE f.id = r.pdf_file_id
        """
    )

    op.drop_constraint(op.f("fk_reports_pdf_file_id_stored_files"), "reports", type_="foreignkey")
    op.drop_index(op.f("ix_reports_pdf_file_id"), table_name="reports")
    op.drop_column("reports", "pdf_file_id")
    op.drop_constraint(op.f("fk_documents_file_id_stored_files"), "documents", type_="foreignkey")
    op.drop_index(op.f("ix_documents_file_id"), table_name="documents")
    op.drop_column("documents", "file_id")
    op.execute("DELETE FROM stored_files WHERE source IN ('pestpac_document', 'report_pdf')")
