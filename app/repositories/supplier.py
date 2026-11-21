from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import Supplier


async def list_suppliers(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    is_active: bool | None,
    supply_category: str | None,
) -> tuple[list[Supplier], int]:
    filters = []
    if is_active is not None:
        filters.append(Supplier.is_active == is_active)
    if supply_category is not None:
        filters.append(Supplier.supply_category == supply_category)

    statement = select(Supplier).where(*filters).order_by(Supplier.supplier_code)
    result = await session.execute(statement.offset(offset).limit(limit))
    suppliers = list(result.scalars().all())

    count_statement = select(func.count()).select_from(Supplier).where(*filters)
    total = await session.scalar(count_statement)
    return suppliers, total or 0


async def get_supplier(
    session: AsyncSession,
    supplier_id: int,
) -> Supplier | None:
    return await session.get(Supplier, supplier_id)


async def create_supplier(session: AsyncSession, supplier: Supplier) -> Supplier:
    session.add(supplier)
    await session.flush()
    return supplier


async def save_supplier(session: AsyncSession, supplier: Supplier) -> Supplier:
    await session.flush()
    return supplier
