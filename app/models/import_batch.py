from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlmodel import Field

from app.models.base import TimestampMixin, utc_now


class ImportBatch(TimestampMixin, table=True):
    __tablename__ = "import_batch"

    id: int | None = Field(default=None, primary_key=True)
    source_filename: str = Field(max_length=255, nullable=False)
    status: str = Field(max_length=40, nullable=False, index=True)
    started_at: datetime = Field(
        default_factory=utc_now,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )
    total_records: int = Field(default=0, ge=0, nullable=False)
    successful_records: int = Field(default=0, ge=0, nullable=False)
    failed_records: int = Field(default=0, ge=0, nullable=False)
    error_summary: str | None = Field(default=None, sa_type=Text)
