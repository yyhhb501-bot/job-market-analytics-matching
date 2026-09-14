"""Board management API (list, add, discover, verify, enable/disable)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.boards import (
    discover_and_verify,
    verify_and_record,
)
from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.models import Board
from apps.api.schemas import (
    BoardCandidate,
    BoardIn,
    BoardOut,
    BoardUpdate,
    DiscoverRequest,
)
from apps.api.security import require_api_key

router = APIRouter(tags=["boards"])


@router.get("/boards", response_model=list[BoardOut])
def list_boards(
    db: Session = Depends(get_db),
    provider: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    country: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[Board]:
    statement = select(Board)
    if provider:
        statement = statement.where(Board.provider == provider)
    if enabled is not None:
        statement = statement.where(Board.enabled.is_(enabled))
    if country:
        statement = statement.where(Board.country == country.upper())
    if q:
        statement = statement.where(
            or_(Board.company_name.ilike(f"%{q}%"), Board.board_token.ilike(f"%{q}%"))
        )
    statement = statement.order_by(Board.provider, Board.board_token).limit(limit)
    return list(db.scalars(statement).all())


@router.post("/boards", response_model=BoardOut, status_code=201, dependencies=[Depends(require_api_key)])
async def create_board(payload: BoardIn, db: Session = Depends(get_db)) -> Board:
    existing = db.scalar(
        select(Board).where(
            Board.provider == payload.provider, Board.board_token == payload.board_token
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="board already exists")
    data = payload.model_dump(exclude={"verify"})
    board = Board(**data)
    db.add(board)
    db.commit()
    db.refresh(board)
    if payload.verify:
        await verify_and_record(db, board, get_settings())
        db.refresh(board)
    return board


@router.patch("/boards/{board_id}", response_model=BoardOut, dependencies=[Depends(require_api_key)])
def update_board(board_id: int, payload: BoardUpdate, db: Session = Depends(get_db)) -> Board:
    board = db.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=404, detail="board not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(board, field, value)
    db.commit()
    db.refresh(board)
    return board


@router.delete("/boards/{board_id}", status_code=204, dependencies=[Depends(require_api_key)])
def delete_board(board_id: int, db: Session = Depends(get_db)) -> None:
    board = db.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=404, detail="board not found")
    db.delete(board)
    db.commit()


@router.post("/boards/{board_id}/verify", response_model=BoardOut, dependencies=[Depends(require_api_key)])
async def verify_one(board_id: int, db: Session = Depends(get_db)) -> Board:
    board = db.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=404, detail="board not found")
    await verify_and_record(db, board, get_settings())
    db.refresh(board)
    return board


@router.post("/boards/discover", response_model=list[BoardCandidate], dependencies=[Depends(require_api_key)])
async def discover(payload: DiscoverRequest, db: Session = Depends(get_db)) -> list[BoardCandidate]:
    settings = get_settings()
    candidates = await discover_and_verify(payload.domain, settings)
    if payload.create:
        for candidate in candidates:
            exists = db.scalar(
                select(Board).where(
                    Board.provider == candidate["provider"],
                    Board.board_token == candidate["board_token"],
                )
            )
            if exists is not None:
                continue
            db.add(
                Board(
                    provider=candidate["provider"],
                    board_token=candidate["board_token"],
                    careers_url=candidate.get("careers_url"),
                    config=candidate.get("config") or {},
                    enabled=bool(candidate.get("verified")),
                    discovery_source="discover",
                )
            )
        db.commit()
    return [BoardCandidate(**candidate) for candidate in candidates]
