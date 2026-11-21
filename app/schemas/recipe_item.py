from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecipeItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    menu_item_id: int = Field(ge=1)
    ingredient_id: int = Field(ge=1)
    quantity_per_portion: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=3,
    )


class RecipeItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    menu_item_id: int | None = Field(default=None, ge=1)
    ingredient_id: int | None = Field(default=None, ge=1)
    quantity_per_portion: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=14,
        decimal_places=3,
    )

    @model_validator(mode="after")
    def validate_patch(self) -> "RecipeItemUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        for field in ("menu_item_id", "ingredient_id", "quantity_per_portion"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class RecipeItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    menu_item_id: int
    ingredient_id: int
    quantity_per_portion: Decimal
    created_at: datetime
    updated_at: datetime


class RecipeItemListResponse(BaseModel):
    items: list[RecipeItemRead]
    total: int
    limit: int
    offset: int
