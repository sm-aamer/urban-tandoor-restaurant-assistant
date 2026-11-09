from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Numeric
from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.branch_stock import BranchStock
    from app.models.recipe_item import RecipeItem
    from app.models.stock_movement import StockMovement
    from app.models.supplier import Supplier


class Ingredient(TimestampMixin, table=True):
    __tablename__ = "ingredient"

    id: int | None = Field(default=None, primary_key=True)
    ingredient_code: str = Field(max_length=64, unique=True, nullable=False)
    name: str = Field(max_length=160, nullable=False)
    category: str | None = Field(default=None, max_length=120)
    unit: str = Field(max_length=32, nullable=False)
    unit_cost_pkr: Decimal | None = Field(
        default=None,
        sa_type=Numeric(14, 2),
    )
    default_reorder_quantity: Decimal | None = Field(
        default=None,
        sa_type=Numeric(14, 3),
    )
    default_target_quantity: Decimal | None = Field(
        default=None,
        sa_type=Numeric(14, 3),
    )
    supplier_id: int | None = Field(
        default=None,
        foreign_key="supplier.id",
        ondelete="RESTRICT",
        index=True,
    )
    is_active: bool = Field(default=True, nullable=False)

    supplier: Optional["Supplier"] = Relationship(back_populates="ingredients")
    branch_stocks: list["BranchStock"] = Relationship(back_populates="ingredient")
    recipe_items: list["RecipeItem"] = Relationship(back_populates="ingredient")
    stock_movements: list["StockMovement"] = Relationship(
        back_populates="ingredient"
    )
