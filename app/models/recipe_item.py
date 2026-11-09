from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Numeric, UniqueConstraint
from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.ingredient import Ingredient
    from app.models.menu_item import MenuItem


class RecipeItem(TimestampMixin, table=True):
    __tablename__ = "recipe_item"
    __table_args__ = (
        UniqueConstraint(
            "menu_item_id",
            "ingredient_id",
            name="uq_recipe_item_menu_ingredient",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    menu_item_id: int = Field(
        foreign_key="menu_item.id",
        ondelete="RESTRICT",
    )
    ingredient_id: int = Field(
        foreign_key="ingredient.id",
        ondelete="RESTRICT",
        index=True,
    )
    quantity_per_portion: Decimal = Field(
        sa_type=Numeric(14, 3),
        nullable=False,
    )

    menu_item: "MenuItem" = Relationship(back_populates="recipe_items")
    ingredient: "Ingredient" = Relationship(back_populates="recipe_items")
