from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IngredientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ingredient_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    category: str | None = Field(default=None, max_length=120)
    unit: str = Field(min_length=1, max_length=32)
    unit_cost_pkr: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    default_reorder_quantity: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=3,
    )
    default_target_quantity: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=3,
    )
    supplier_id: int | None = Field(default=None, ge=1)
    is_active: bool = True


class IngredientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ingredient_code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    category: str | None = Field(default=None, max_length=120)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    unit_cost_pkr: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )
    default_reorder_quantity: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=3,
    )
    default_target_quantity: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=3,
    )
    supplier_id: int | None = Field(default=None, ge=1)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "IngredientUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        for field in ("ingredient_code", "name", "unit", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class IngredientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ingredient_code: str
    name: str
    category: str | None
    unit: str
    unit_cost_pkr: Decimal | None
    default_reorder_quantity: Decimal | None
    default_target_quantity: Decimal | None
    supplier_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class IngredientListResponse(BaseModel):
    items: list[IngredientRead]
    total: int
    limit: int
    offset: int
