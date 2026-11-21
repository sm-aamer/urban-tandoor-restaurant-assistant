from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_session
from app.schemas.branch import (
    BranchCreate,
    BranchListResponse,
    BranchRead,
    BranchUpdate,
)
from app.services import branch as branch_service

router = APIRouter(prefix="/branches", tags=["branches"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=BranchListResponse)
async def list_branches(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    is_active: bool | None = None,
) -> BranchListResponse:
    branches, total = await branch_service.list_branches(
        session,
        limit=limit,
        offset=offset,
        is_active=is_active,
    )
    return BranchListResponse(
        items=[BranchRead.model_validate(branch) for branch in branches],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{branch_id}", response_model=BranchRead)
async def get_branch(
    branch_id: int,
    session: SessionDependency,
) -> BranchRead:
    try:
        branch = await branch_service.get_branch(session, branch_id)
    except branch_service.BranchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found.",
        ) from exc
    return BranchRead.model_validate(branch)


@router.post(
    "",
    response_model=BranchRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_branch(
    branch_in: BranchCreate,
    session: SessionDependency,
) -> BranchRead:
    try:
        branch = await branch_service.create_branch(session, branch_in)
    except branch_service.BranchConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A branch with this branch code already exists.",
        ) from exc
    return BranchRead.model_validate(branch)


@router.patch("/{branch_id}", response_model=BranchRead)
async def update_branch(
    branch_id: int,
    branch_in: BranchUpdate,
    session: SessionDependency,
) -> BranchRead:
    try:
        branch = await branch_service.update_branch(
            session,
            branch_id,
            branch_in,
        )
    except branch_service.BranchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found.",
        ) from exc
    except branch_service.BranchConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A branch with this branch code already exists.",
        ) from exc
    return BranchRead.model_validate(branch)


@router.delete(
    "/{branch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_branch(
    branch_id: int,
    session: SessionDependency,
) -> Response:
    try:
        await branch_service.deactivate_branch(session, branch_id)
    except branch_service.BranchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
