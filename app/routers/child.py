"""孩子端：今日打卡、我的记录。"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session as DBSession
from sqlmodel import select

from ..auth import csrf_protect, require_child
from ..config import now_local
from ..database import get_session
from ..models import PointTransaction, Rule, User
from ..services import ledger
from ..templating import render

router = APIRouter(dependencies=[Depends(csrf_protect)])


def _task_items(db: DBSession, child_id: int, period: str) -> list[dict]:
    now = now_local()
    stmt = (
        select(Rule)
        .where(Rule.active == True, Rule.period == period)  # noqa: E712
        .order_by(Rule.sort_order, Rule.id)
    )
    items = []
    for rule in db.exec(stmt).all():
        stats = ledger.period_stats(db, child_id, rule, now)
        stats["full"] = stats["total"] >= stats["limit"]
        items.append({"rule": rule, **stats})
    return items


@router.get("/")
def today(
    request: Request,
    m: str = "",
    child: User = Depends(require_child),
    db: DBSession = Depends(get_session),
):
    start, end = ledger.day_bounds(now_local().date())
    daily = _task_items(db, child.id, "daily")
    weekly = _task_items(db, child.id, "weekly")
    pending_total = sum(it["pending"] for it in daily) + sum(it["pending"] for it in weekly)
    return render(
        request,
        "child/today.html",
        {
            "child_name": child.name,
            "balance": ledger.balance(db, child.id),
            "today_points": ledger.sum_confirmed_between(db, child.id, start, end),
            "daily": daily,
            "weekly": weekly,
            "pending_total": pending_total,
            "m": m,
        },
    )


@router.post("/checkin/{rule_id}")
def checkin(
    rule_id: int,
    request: Request,
    child: User = Depends(require_child),
    db: DBSession = Depends(get_session),
):
    rule = db.get(Rule, rule_id)
    if rule is None:
        return RedirectResponse("/", status_code=303)
    try:
        ledger.create_checkin(db, child.id, rule, child.id)
        db.commit()
    except ValueError as e:
        db.rollback()
        return RedirectResponse(f"/?m={quote(str(e))}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.get("/history")
def history(
    request: Request,
    child: User = Depends(require_child),
    db: DBSession = Depends(get_session),
):
    stmt = (
        select(PointTransaction)
        .where(PointTransaction.child_id == child.id)
        .order_by(PointTransaction.created_at.desc(), PointTransaction.id.desc())
        .limit(100)
    )
    txs = list(db.exec(stmt).all())
    rule_map = {r.id: r for r in db.exec(select(Rule)).all()}
    rows = []
    for tx in txs:
        rule = rule_map.get(tx.rule_id) if tx.rule_id else None
        rows.append({
            "tx": tx,
            "name": rule.name if rule else (tx.note or "自定义"),
            "icon": rule.icon if rule else "✍️",
        })
    return render(
        request,
        "child/history.html",
        {"rows": rows, "balance": ledger.balance(db, child.id)},
    )
