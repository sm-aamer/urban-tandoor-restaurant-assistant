from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Numeric, UniqueConstraint
from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.branch import Branch
    from app.models.ingredient import Ingredient


class BranchStock(TimestampMixin, table=True):
    __tablename__ = "branch_stock"
    __table_args__ = (
        UniqueConstraint(
            "branch_id",
            "ingredient_id",
            name="uq_branch_stock_branch_ingredient",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    branch_id: int = Field(
        foreign_key="branch.id",
        ondelete="RESTRICT",
    )
    ingredient_id: int = Field(
        foreign_key="ingredient.id",
        ondelete="RESTRICT",
        index=True,
    )
    quantity_on_hand: Decimal = Field(
        sa_type=Numeric(14, 3),
        nullable=False,
    )
    reserved_quantity: Decimal = Field(
        default=Decimal(0),
        sa_type=Numeric(14, 3),
        nullable=False,
    )
    reorder_level: Decimal | None = Field(
        default=None,
        sa_type=Numeric(14, 3),
    )
    target_stock: Decimal | None = Field(
        default=None,
        sa_type=Numeric(14, 3),
    )

    branch: "Branch" = Relationship(back_populates="stock_records")
    ingredient: "Ingredient" = Relationship(back_populates="branch_stocks")
