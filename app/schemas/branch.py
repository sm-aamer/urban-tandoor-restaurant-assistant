from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BranchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    branch_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=300)
    table_count: int | None = Field(default=None, ge=0)
    seat_capacity: int | None = Field(default=None, ge=0)
    operating_hours: str | None = Field(default=None, max_length=100)
    is_active: bool = True


class BranchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    branch_code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=300)
    table_count: int | None = Field(default=None, ge=0)
    seat_capacity: int | None = Field(default=None, ge=0)
    operating_hours: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "BranchUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        for field in ("branch_code", "name", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class BranchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    branch_code: str
    name: str
    address: str | None
    table_count: int | None
    seat_capacity: int | None
    operating_hours: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BranchListResponse(BaseModel):
    items: list[BranchRead]
    total: int
    limit: int
    offset: int
