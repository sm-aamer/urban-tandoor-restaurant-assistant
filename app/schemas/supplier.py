from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    supplier_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    supply_category: str | None = Field(default=None, max_length=120)
    contact: str | None = Field(default=None, max_length=300)
    verification_status: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    supplier_code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    supply_category: str | None = Field(default=None, max_length=120)
    contact: str | None = Field(default=None, max_length=300)
    verification_status: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "SupplierUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        for field in ("supplier_code", "name"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_code: str
    name: str
    supply_category: str | None
    contact: str | None
    verification_status: str | None
    is_active: bool | None
    created_at: datetime
    updated_at: datetime


class SupplierListResponse(BaseModel):
    items: list[SupplierRead]
    total: int
    limit: int
    offset: int
