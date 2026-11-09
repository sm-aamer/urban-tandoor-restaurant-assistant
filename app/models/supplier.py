from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.ingredient import Ingredient
    from app.models.stock_movement import StockMovement


class Supplier(TimestampMixin, table=True):
    __tablename__ = "supplier"

    id: int | None = Field(default=None, primary_key=True)
    supplier_code: str = Field(max_length=64, unique=True, nullable=False)
    name: str = Field(max_length=160, nullable=False)
    supply_category: str | None = Field(default=None, max_length=120)
    contact: str | None = Field(default=None, max_length=300)
    verification_status: str | None = Field(default=None, max_length=80)
    is_active: bool | None = Field(default=None)

    ingredients: list["Ingredient"] = Relationship(back_populates="supplier")
    stock_movements: list["StockMovement"] = Relationship(back_populates="supplier")
