from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Branch
from app.repositories import branch as branch_repository
from app.schemas.branch import BranchCreate, BranchUpdate


class BranchNotFoundError(Exception):
    pass


class BranchConflictError(Exception):
    pass


async def list_branches(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    is_active: bool | None,
) -> tuple[list[Branch], int]:
    return await branch_repository.list_branches(
        session,
        limit=limit,
        offset=offset,
        is_active=is_active,
    )


async def get_branch(session: AsyncSession, branch_id: int) -> Branch:
    branch = await branch_repository.get_branch(session, branch_id)
    if branch is None:
        raise BranchNotFoundError
    return branch


async def create_branch(
    session: AsyncSession,
    branch_in: BranchCreate,
) -> Branch:
    try:
        async with session.begin():
            branch = Branch(**branch_in.model_dump())
            await branch_repository.create_branch(session, branch)
    except IntegrityError as exc:
        raise BranchConflictError from exc
    return branch


async def update_branch(
    session: AsyncSession,
    branch_id: int,
    branch_in: BranchUpdate,
) -> Branch:
    try:
        async with session.begin():
            branch = await branch_repository.get_branch(session, branch_id)
            if branch is None:
                raise BranchNotFoundError
            for field, value in branch_in.model_dump(exclude_unset=True).items():
                setattr(branch, field, value)
            await branch_repository.save_branch(session, branch)
    except IntegrityError as exc:
        raise BranchConflictError from exc
    return branch


async def deactivate_branch(session: AsyncSession, branch_id: int) -> None:
    async with session.begin():
        branch = await branch_repository.get_branch(session, branch_id)
        if branch is None:
            raise BranchNotFoundError
        branch.is_active = False
        await branch_repository.save_branch(session, branch)
