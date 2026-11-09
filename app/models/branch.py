from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.branch_stock import BranchStock
    from app.models.menu_availability import MenuAvailability
    from app.models.restaurant_document import RestaurantDocument
    from app.models.stock_movement import StockMovement


class Branch(TimestampMixin, table=True):
    __tablename__ = "branch"

    id: int | None = Field(default=None, primary_key=True)
    branch_code: str = Field(max_length=64, unique=True, nullable=False)
    name: str = Field(max_length=120, nullable=False)
    address: str | None = Field(default=None, max_length=300)
    table_count: int | None = Field(default=None, ge=0)
    seat_capacity: int | None = Field(default=None, ge=0)
    operating_hours: str | None = Field(default=None, max_length=100)
    is_active: bool = Field(default=True, nullable=False)

    stock_records: list["BranchStock"] = Relationship(back_populates="branch")
    menu_availability: list["MenuAvailability"] = Relationship(
        back_populates="branch"
    )
    stock_movements: list["StockMovement"] = Relationship(back_populates="branch")
    documents: list["RestaurantDocument"] = Relationship(back_populates="branch")
