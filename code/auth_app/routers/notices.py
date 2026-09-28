"""CRUD for recall notices, plus the two Part 3 list endpoints.

    GET    /api/notices/naive?page=&page_size=   1 + N queries (intentionally slow)
    GET    /api/notices/fixed?page=&page_size=   1 query with a JOIN
    GET    /api/notices?page=&page_size=         same as fixed; used by the React Home page
    GET    /api/notices/{id}
    POST   /api/notices
    PUT    /api/notices/{id}
    DELETE /api/notices/{id}

Every route requires a logged-in session.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

import config
import query_counter
from database import get_db
from deps import require_session
from models import Firm, RecallNotice
from schemas import FirmOut, NoticeIn, NoticeOut, NoticePage

router = APIRouter(prefix="/api/notices", tags=["notices"],
                   dependencies=[Depends(require_session)])

PageNo = Query(1, ge=1)
PageSize = Query(50, ge=1, le=config.MAX_PAGE_SIZE)


def page_query(page: int, page_size: int):
    """Newest first. id breaks ties so every page has a stable order."""
    return (
        select(RecallNotice)
        .order_by(RecallNotice.recall_date.desc(), RecallNotice.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )


def mark_list_start(response: Response) -> int:
    """SQL statements already spent (on the session check) before the list work."""
    counter = query_counter.current()
    return counter.total if counter else 0


def mark_list_end(response: Response, before: int) -> None:
    counter = query_counter.current()
    if counter:
        response.headers["X-SQL-List"] = str(counter.total - before)


# ---- Part 3: the two list versions ------------------------------------------

@router.get("/naive", response_model=NoticePage)
def list_naive(response: Response, page: int = PageNo, page_size: int = PageSize,
               db: Session = Depends(get_db)):
    """N+1 on purpose: one query for the page, then one query per row for its firm.

    db.execute(select(...)) always goes to MySQL. db.get(Firm, id) would not:
    it returns an already-loaded firm from the Session's identity map without
    SQL, which would hide part of the N+1 cost and make the count depend on
    how many firms repeat on the page.
    """
    before = mark_list_start(response)
    notices = db.execute(page_query(page, page_size)).scalars().all()      # 1 query

    items = []
    for n in notices:                                                        # N queries
        firm = None
        if n.firm_id is not None:
            firm = db.execute(select(Firm).where(Firm.id == n.firm_id)).scalar_one()
        items.append(NoticeOut(id=n.id, product_name=n.product_name, category=n.category,
                               recall_date=n.recall_date,
                               firm=FirmOut.model_validate(firm) if firm else None))
    mark_list_end(response, before)
    return NoticePage(version="naive", page=page, page_size=page_size, items=items)


def fixed_items(db: Session, page: int, page_size: int):
    stmt = page_query(page, page_size).options(joinedload(RecallNotice.firm))
    return db.execute(stmt).scalars().all()      # 1 query: ... LEFT OUTER JOIN firms


@router.get("/fixed", response_model=NoticePage)
def list_fixed(response: Response, page: int = PageNo, page_size: int = PageSize,
               db: Session = Depends(get_db)):
    """Same rows and same JSON as /naive, loaded with a single JOIN."""
    before = mark_list_start(response)
    items = fixed_items(db, page, page_size)
    mark_list_end(response, before)
    return NoticePage(version="fixed", page=page, page_size=page_size, items=items)


@router.get("", response_model=NoticePage)
def list_notices(response: Response, page: int = PageNo, page_size: int = PageSize,
                 db: Session = Depends(get_db)):
    """View all records, one page at a time (the React Home page uses this)."""
    return list_fixed(response, page, page_size, db)


# ---- single-record CRUD -----------------------------------------------------

def load_notice(db: Session, notice_id: int) -> RecallNotice:
    stmt = (select(RecallNotice).options(joinedload(RecallNotice.firm))
            .where(RecallNotice.id == notice_id))
    notice = db.execute(stmt).scalar_one_or_none()
    if notice is None:
        raise HTTPException(status_code=404, detail=f"Recall notice {notice_id} not found")
    return notice


def check_firm(db: Session, firm_id):
    if firm_id is not None and db.get(Firm, firm_id) is None:
        raise HTTPException(status_code=422, detail=f"firm_id {firm_id} does not exist")


@router.get("/{notice_id}", response_model=NoticeOut)
def get_notice(notice_id: int, db: Session = Depends(get_db)):
    return load_notice(db, notice_id)


@router.post("", response_model=NoticeOut, status_code=201)
def create_notice(payload: NoticeIn, db: Session = Depends(get_db)):
    check_firm(db, payload.firm_id)
    notice = RecallNotice(
        product_name=payload.product_name.strip(),
        category=payload.category,
        recall_date=payload.recall_date or date.today(),
        firm_id=payload.firm_id,
    )
    db.add(notice)
    db.commit()                        # MySQL assigns the AUTO_INCREMENT id here
    return load_notice(db, notice.id)


@router.put("/{notice_id}", response_model=NoticeOut)
def update_notice(notice_id: int, payload: NoticeIn, db: Session = Depends(get_db)):
    notice = load_notice(db, notice_id)
    check_firm(db, payload.firm_id)
    notice.product_name = payload.product_name.strip()
    notice.category = payload.category
    if payload.recall_date is not None:
        notice.recall_date = payload.recall_date
    if "firm_id" in payload.model_fields_set:   # only change the firm when it was sent
        notice.firm_id = payload.firm_id
    db.commit()
    db.expire(notice)                  # reload so the response shows the new firm
    return load_notice(db, notice_id)


@router.delete("/{notice_id}", status_code=204)
def delete_notice(notice_id: int, db: Session = Depends(get_db)):
    notice = load_notice(db, notice_id)
    db.delete(notice)
    db.commit()
    return Response(status_code=204)
