from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Text
from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.branch import Branch


class RestaurantDocument(TimestampMixin, table=True):
    __tablename__ = "restaurant_document"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=255, nullable=False)
    document_type: str = Field(max_length=80, nullable=False, index=True)
    content: str = Field(sa_type=Text, nullable=False)
    source_identifier: str | None = Field(default=None, max_length=255, index=True)
    branch_id: int | None = Field(
        default=None,
        foreign_key="branch.id",
        ondelete="SET NULL",
        index=True,
    )
    content_hash: str = Field(max_length=128, index=True, nullable=False)
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_type=JSON,
        nullable=False,
    )
    embedding_status: str | None = Field(default=None, max_length=40)

    branch: Optional["Branch"] = Relationship(back_populates="documents")
