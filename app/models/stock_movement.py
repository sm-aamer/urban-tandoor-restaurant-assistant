from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Index, Numeric
from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.branch import Branch
    from app.models.ingredient import Ingredient
    from app.models.supplier import Supplier


class StockMovement(TimestampMixin, table=True):
    __tablename__ = "stock_movement"
    __table_args__ = (
        Index("ix_stock_movement_branch_date", "branch_id", "movement_date"),
        Index("ix_stock_movement_ingredient_date", "ingredient_id", "movement_date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    movement_code: str | None = Field(default=None, max_length=64, unique=True)
    branch_id: int = Field(
        foreign_key="branch.id",
        ondelete="RESTRICT",
    )
    ingredient_id: int = Field(
        foreign_key="ingredient.id",
        ondelete="RESTRICT",
    )
    supplier_id: int | None = Field(
        default=None,
        foreign_key="supplier.id",
        ondelete="RESTRICT",
        index=True,
    )
    movement_type: str = Field(max_length=40, nullable=False)
    quantity: Decimal = Field(sa_type=Numeric(14, 3), nullable=False)
    movement_date: date = Field(nullable=False)
    reference: str | None = Field(default=None, max_length=160)
    reason: str | None = Field(default=None)
    data_type: str | None = Field(default=None, max_length=40)

    branch: "Branch" = Relationship(back_populates="stock_movements")
    ingredient: "Ingredient" = Relationship(back_populates="stock_movements")
    supplier: Optional["Supplier"] = Relationship(back_populates="stock_movements")
