from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Supplier
from app.repositories import supplier as supplier_repository
from app.schemas.supplier import SupplierCreate, SupplierUpdate


class SupplierNotFoundError(Exception):
    pass


class SupplierConflictError(Exception):
    pass


async def list_suppliers(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    is_active: bool | None,
    supply_category: str | None,
) -> tuple[list[Supplier], int]:
    return await supplier_repository.list_suppliers(
        session,
        limit=limit,
        offset=offset,
        is_active=is_active,
        supply_category=supply_category,
    )


async def get_supplier(session: AsyncSession, supplier_id: int) -> Supplier:
    supplier = await supplier_repository.get_supplier(session, supplier_id)
    if supplier is None:
        raise SupplierNotFoundError
    return supplier


async def create_supplier(
    session: AsyncSession,
    supplier_in: SupplierCreate,
) -> Supplier:
    try:
        async with session.begin():
            supplier = Supplier(**supplier_in.model_dump())
            await supplier_repository.create_supplier(session, supplier)
    except IntegrityError as exc:
        raise SupplierConflictError from exc
    return supplier


async def update_supplier(
    session: AsyncSession,
    supplier_id: int,
    supplier_in: SupplierUpdate,
) -> Supplier:
    try:
        async with session.begin():
            supplier = await supplier_repository.get_supplier(session, supplier_id)
            if supplier is None:
                raise SupplierNotFoundError
            for field, value in supplier_in.model_dump(exclude_unset=True).items():
                setattr(supplier, field, value)
            await supplier_repository.save_supplier(session, supplier)
    except IntegrityError as exc:
        raise SupplierConflictError from exc
    return supplier


async def deactivate_supplier(session: AsyncSession, supplier_id: int) -> None:
    async with session.begin():
        supplier = await supplier_repository.get_supplier(session, supplier_id)
        if supplier is None:
            raise SupplierNotFoundError
        supplier.is_active = False
        await supplier_repository.save_supplier(session, supplier)
