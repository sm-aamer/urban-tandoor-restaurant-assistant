from typing import TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.branch import Branch
    from app.models.menu_item import MenuItem


class MenuAvailability(TimestampMixin, table=True):
    __tablename__ = "menu_availability"
    __table_args__ = (
        UniqueConstraint(
            "branch_id",
            "menu_item_id",
            name="uq_menu_availability_branch_menu_item",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    branch_id: int = Field(
        foreign_key="branch.id",
        ondelete="RESTRICT",
    )
    menu_item_id: int = Field(
        foreign_key="menu_item.id",
        ondelete="RESTRICT",
        index=True,
    )
    is_available: bool | None = Field(default=None)

    branch: "Branch" = Relationship(back_populates="menu_availability")
    menu_item: "MenuItem" = Relationship(back_populates="availability_records")
