"""CRUD for firms (the related entity), plus the relationship query.

    GET    /api/firms?page=&page_size=          all firms, one page at a time
    GET    /api/firms/{id}
    POST   /api/firms
    PUT    /api/firms/{id}
    DELETE /api/firms/{id}                      409 while the firm still has notices
    GET    /api/firms/{id}/notices?page=&page_size=    every notice of one firm

Every route requires a logged-in session.

Status codes: 404 unknown id, 422 body fails the schema (FastAPI does this
before the function runs), 409 the request is valid but MySQL refuses it
because of a UNIQUE or FOREIGN KEY constraint.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

import config
from database import get_db
from deps import require_session
from models import Firm, RecallNotice
from schemas import FirmIn, FirmNoticesPage, FirmOut, FirmPage

router = APIRouter(prefix="/api/firms", tags=["firms"],
                   dependencies=[Depends(require_session)])

PageNo = Query(1, ge=1)
PageSize = Query(20, ge=1, le=config.MAX_PAGE_SIZE)

# MySQL error numbers carried inside SQLAlchemy's IntegrityError
DUPLICATE_ENTRY = 1062        # a UNIQUE constraint would be broken
ROW_IS_REFERENCED = 1451      # ON DELETE RESTRICT: child rows still point here


def mysql_code(exc: IntegrityError) -> int:
    return exc.orig.args[0]


def load_firm(db: Session, firm_id: int) -> Firm:
    firm = db.get(Firm, firm_id)
    if firm is None:
        raise HTTPException(status_code=404, detail=f"Firm {firm_id} not found")
    return firm


def save(db: Session, email: str) -> None:
    """Commit; turn a duplicate contact_email into 409 instead of a 500 crash."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if mysql_code(exc) == DUPLICATE_ENTRY:
            raise HTTPException(status_code=409,
                                detail=f"contact_email {email} is already used by another firm")
        raise


# ---- list and read ---------------------------------------------------------

@router.get("", response_model=FirmPage)
def list_firms(page: int = PageNo, page_size: int = PageSize, db: Session = Depends(get_db)):
    total = db.execute(select(func.count()).select_from(Firm)).scalar_one()
    stmt = select(Firm).order_by(Firm.id).limit(page_size).offset((page - 1) * page_size)
    items = db.execute(stmt).scalars().all()
    return FirmPage(page=page, page_size=page_size, total=total, items=items)


@router.get("/{firm_id}", response_model=FirmOut)
def get_firm(firm_id: int, db: Session = Depends(get_db)):
    return load_firm(db, firm_id)


# ---- the relationship query --------------------------------------------------

@router.get("/{firm_id}/notices", response_model=FirmNoticesPage)
def list_firm_notices(firm_id: int, page: int = PageNo, page_size: int = PageSize,
                      db: Session = Depends(get_db)):
    """All recall notices issued by one firm, newest first."""
    firm = load_firm(db, firm_id)                              # 404 if the firm is unknown
    total = db.execute(select(func.count()).select_from(RecallNotice)
                       .where(RecallNotice.firm_id == firm_id)).scalar_one()
    stmt = (select(RecallNotice)
            .where(RecallNotice.firm_id == firm_id)
            .options(joinedload(RecallNotice.firm))            # needed: firm is lazy="raise"
            .order_by(RecallNotice.recall_date.desc(), RecallNotice.id.desc())
            .limit(page_size).offset((page - 1) * page_size))
    items = db.execute(stmt).scalars().all()
    return FirmNoticesPage(firm=firm, page=page, page_size=page_size, total=total, items=items)


# ---- create, update, delete ----------------------------------------------------

@router.post("", response_model=FirmOut, status_code=201)
def create_firm(payload: FirmIn, db: Session = Depends(get_db)):
    email = payload.contact_email.lower()
    firm = Firm(name=payload.name.strip(), state=payload.state, contact_email=email)
    db.add(firm)
    save(db, email)
    db.refresh(firm)               # read back id, created_at, updated_at from MySQL
    return firm


@router.put("/{firm_id}", response_model=FirmOut)
def update_firm(firm_id: int, payload: FirmIn, db: Session = Depends(get_db)):
    firm = load_firm(db, firm_id)
    email = payload.contact_email.lower()
    firm.name = payload.name.strip()
    firm.state = payload.state
    firm.contact_email = email
    save(db, email)
    db.refresh(firm)               # updated_at was changed by MySQL
    return firm


@router.delete("/{firm_id}", status_code=204)
def delete_firm(firm_id: int, db: Session = Depends(get_db)):
    """Delete a firm - unless notices still belong to it.

    The check is not done in Python first. The DELETE is sent, and MySQL's
    ON DELETE RESTRICT foreign key refuses it (error 1451). That way the rule
    holds even if two requests arrive at the same moment.
    """
    firm = load_firm(db, firm_id)
    try:
        db.delete(firm)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if mysql_code(exc) != ROW_IS_REFERENCED:
            raise
        count = db.execute(select(func.count()).select_from(RecallNotice)
                           .where(RecallNotice.firm_id == firm_id)).scalar_one()
        raise HTTPException(
            status_code=409,
            detail=f"Firm {firm_id} still has {count} recall notice(s); "
                   f"delete or reassign them first")
    return Response(status_code=204)
