from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_session
from app.schemas.supplier import (
    SupplierCreate,
    SupplierListResponse,
    SupplierRead,
    SupplierUpdate,
)
from app.services import supplier as supplier_service

router = APIRouter(prefix="/suppliers", tags=["suppliers"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=SupplierListResponse)
async def list_suppliers(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    is_active: bool | None = None,
    supply_category: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
) -> SupplierListResponse:
    suppliers, total = await supplier_service.list_suppliers(
        session,
        limit=limit,
        offset=offset,
        is_active=is_active,
        supply_category=supply_category,
    )
    return SupplierListResponse(
        items=[SupplierRead.model_validate(supplier) for supplier in suppliers],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{supplier_id}", response_model=SupplierRead)
async def get_supplier(
    supplier_id: int,
    session: SessionDependency,
) -> SupplierRead:
    try:
        supplier = await supplier_service.get_supplier(session, supplier_id)
    except supplier_service.SupplierNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found.",
        ) from exc
    return SupplierRead.model_validate(supplier)


@router.post(
    "",
    response_model=SupplierRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_supplier(
    supplier_in: SupplierCreate,
    session: SessionDependency,
) -> SupplierRead:
    try:
        supplier = await supplier_service.create_supplier(session, supplier_in)
    except supplier_service.SupplierConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A supplier with this supplier code already exists.",
        ) from exc
    return SupplierRead.model_validate(supplier)


@router.patch("/{supplier_id}", response_model=SupplierRead)
async def update_supplier(
    supplier_id: int,
    supplier_in: SupplierUpdate,
    session: SessionDependency,
) -> SupplierRead:
    try:
        supplier = await supplier_service.update_supplier(
            session,
            supplier_id,
            supplier_in,
        )
    except supplier_service.SupplierNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found.",
        ) from exc
    except supplier_service.SupplierConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A supplier with this supplier code already exists.",
        ) from exc
    return SupplierRead.model_validate(supplier)


@router.delete(
    "/{supplier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_supplier(
    supplier_id: int,
    session: SessionDependency,
) -> Response:
    try:
        await supplier_service.deactivate_supplier(session, supplier_id)
    except supplier_service.SupplierNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
