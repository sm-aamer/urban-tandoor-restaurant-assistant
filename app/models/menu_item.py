from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Numeric
from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.menu_availability import MenuAvailability
    from app.models.recipe_item import RecipeItem


class MenuItem(TimestampMixin, table=True):
    __tablename__ = "menu_item"

    id: int | None = Field(default=None, primary_key=True)
    menu_code: str = Field(max_length=64, unique=True, nullable=False)
    name: str = Field(max_length=180, nullable=False)
    category: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None)
    price_pkr: Decimal | None = Field(
        default=None,
        ge=0,
        sa_type=Numeric(14, 2),
    )
    is_active: bool = Field(default=True, nullable=False)

    recipe_items: list["RecipeItem"] = Relationship(back_populates="menu_item")
    availability_records: list["MenuAvailability"] = Relationship(
        back_populates="menu_item"
    )
