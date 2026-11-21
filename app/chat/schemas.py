from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolArguments(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )


class PaginatedToolArguments(ToolArguments):
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10_000)


class ListBranchesArguments(PaginatedToolArguments):
    is_active: bool | None = None


class RecordIdArguments(ToolArguments):
    record_id: int = Field(ge=1)


class ListSuppliersArguments(PaginatedToolArguments):
    is_active: bool | None = None


class SearchIngredientsArguments(PaginatedToolArguments):
    query: str | None = Field(default=None, min_length=1, max_length=100)
    category: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class SearchMenuItemsArguments(PaginatedToolArguments):
    query: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class RecipeIngredientsArguments(PaginatedToolArguments):
    menu_item_id: int = Field(ge=1)


class MenuAvailabilityArguments(PaginatedToolArguments):
    branch_id: int = Field(ge=1)
    menu_item_id: int | None = Field(default=None, ge=1)


class StockMovementArguments(PaginatedToolArguments):
    branch_id: int | None = Field(default=None, ge=1)
    ingredient_id: int | None = Field(default=None, ge=1)
    movement_type: str | None = Field(default=None, min_length=1, max_length=40)
    start_date: date | None = Field(default=None, strict=False)
    end_date: date | None = Field(default=None, strict=False)

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date must be on or before end_date.")
        return self
