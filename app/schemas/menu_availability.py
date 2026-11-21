from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MenuAvailabilityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: int = Field(ge=1)
    menu_item_id: int = Field(ge=1)
    is_available: bool | None = None


class MenuAvailabilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: int | None = Field(default=None, ge=1)
    menu_item_id: int | None = Field(default=None, ge=1)
    is_available: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "MenuAvailabilityUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        for field in ("branch_id", "menu_item_id"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class MenuAvailabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    branch_id: int
    menu_item_id: int
    is_available: bool | None
    created_at: datetime
    updated_at: datetime


class MenuAvailabilityListResponse(BaseModel):
    items: list[MenuAvailabilityRead]
    total: int
    limit: int
    offset: int
