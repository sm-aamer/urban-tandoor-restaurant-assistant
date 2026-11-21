from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MenuItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    menu_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=180)
    category: str | None = Field(default=None, max_length=120)
    description: str | None = None
    price_pkr: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )
    is_active: bool = True


class MenuItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    menu_code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=180)
    category: str | None = Field(default=None, max_length=120)
    description: str | None = None
    price_pkr: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "MenuItemUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        for field in ("menu_code", "name", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class MenuItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    menu_code: str
    name: str
    category: str | None
    description: str | None
    price_pkr: Decimal | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MenuItemListResponse(BaseModel):
    items: list[MenuItemRead]
    total: int
    limit: int
    offset: int
