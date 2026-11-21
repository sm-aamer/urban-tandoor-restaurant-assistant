from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import Branch


async def list_branches(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    is_active: bool | None,
) -> tuple[list[Branch], int]:
    filters = []
    if is_active is not None:
        filters.append(Branch.is_active == is_active)

    statement = select(Branch).where(*filters).order_by(Branch.branch_code)
    result = await session.execute(statement.offset(offset).limit(limit))
    branches = list(result.scalars().all())

    count_statement = select(func.count()).select_from(Branch).where(*filters)
    total = await session.scalar(count_statement)
    return branches, total or 0


async def get_branch(
    session: AsyncSession,
    branch_id: int,
) -> Branch | None:
    return await session.get(Branch, branch_id)


async def create_branch(session: AsyncSession, branch: Branch) -> Branch:
    session.add(branch)
    await session.flush()
    return branch


async def save_branch(session: AsyncSession, branch: Branch) -> Branch:
    await session.flush()
    return branch
