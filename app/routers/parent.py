"""家长端：审核、手动记账、流水、规则管理、设置。"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlmodel import Session as DBSession
from sqlmodel import select

from ..auth import csrf_protect, require_parent
from ..config import now_local
from ..database import get_session
from ..models import PointTransaction, Rule, User
from ..security import hash_secret, verify_secret
from ..services import ledger
from ..templating import render

router = APIRouter(prefix="/parent", dependencies=[Depends(csrf_protect)])

PAGE_SIZE = 50


def _enrich(db: DBSession, txs: list[PointTransaction]) -> list[dict]:
    """给流水补上规则名/图标/孩子名，供模板渲染。"""
    rule_ids = {t.rule_id for t in txs if t.rule_id}
    child_ids = {t.child_id for t in txs}
    rules = {r.id: r for r in db.exec(select(Rule).where(Rule.id.in_(rule_ids))).all()} if rule_ids else {}
    children = {u.id: u for u in db.exec(select(User).where(User.id.in_(child_ids))).all()} if child_ids else {}
    rev = ledger.reversed_ids(db, [t.id for t in txs])
    rows = []
    for t in txs:
        rule = rules.get(t.rule_id) if t.rule_id else None
        child = children.get(t.child_id)
        rows.append({
            "tx": t,
            "rule": rule,
            "child": child,
            "name": rule.name if rule else (t.note or "自定义"),
            "icon": rule.icon if rule else "✍️",
            "reversed": t.id in rev,
        })
    return rows


@router.get("")
def dashboard(
    request: Request,
    parent: User = Depends(require_parent),
    db: DBSession = Depends(get_session),
):
    child = ledger.get_child(db)
    now = now_local()
    day_s, day_e = ledger.day_bounds(now.date())
    week_s, week_e = ledger.week_bounds(now.date())
    pendings = ledger.pending_transactions(db)
    rows = _enrich(db, pendings)
    ctx = {
        "rows": rows,
        "balance": ledger.balance(db, child.id) if child else 0,
        "week_points": ledger.sum_confirmed_between(db, child.id, week_s, week_e) if child else 0,
        "today_points": ledger.sum_confirmed_between(db, child.id, day_s, day_e) if child else 0,
        "child": child,
        "m": request.query_params.get("m", ""),
    }
    return render(request, "parent/dashboard.html", ctx)


@router.post("/tx/{tx_id}/confirm")
def confirm_tx(tx_id: int, db: DBSession = Depends(get_session), parent: User = Depends(require_parent)):
    tx = db.get(PointTransaction, tx_id)
    if tx is not None:
        try:
            ledger.confirm_tx(db, tx)
            db.commit()
        except ValueError as e:
            db.rollback()
            return RedirectResponse(f"/parent?m={quote(str(e))}", status_code=303)
    return RedirectResponse("/parent", status_code=303)


@router.post("/tx/{tx_id}/reject")
def reject_tx(tx_id: int, db: DBSession = Depends(get_session), parent: User = Depends(require_parent)):
    tx = db.get(PointTransaction, tx_id)
    if tx is not None:
        try:
            ledger.reject_tx(db, tx)
            db.commit()
        except ValueError as e:
            db.rollback()
            return RedirectResponse(f"/parent?m={quote(str(e))}", status_code=303)
    return RedirectResponse("/parent", status_code=303)


@router.post("/tx/{tx_id}/reverse")
def reverse_tx(
    tx_id: int,
    note: str = Form(""),
    db: DBSession = Depends(get_session),
    parent: User = Depends(require_parent),
):
    tx = db.get(PointTransaction, tx_id)
    if tx is not None:
        try:
            ledger.reverse_tx(db, tx, parent.id, note)
            db.commit()
        except ValueError as e:
            db.rollback()
            return RedirectResponse(f"/parent/ledger?m={quote(str(e))}", status_code=303)
    return RedirectResponse("/parent/ledger", status_code=303)


@router.get("/entry")
def entry_page(
    request: Request,
    parent: User = Depends(require_parent),
    db: DBSession = Depends(get_session),
):
    child = ledger.get_child(db)
    rules = db.exec(
        select(Rule).where(Rule.active == True).order_by(Rule.sort_order, Rule.id)  # noqa: E712
    ).all()
    return render(request, "parent/entry.html", {"child": child, "rules": rules, "error": ""})


@router.post("/entry")
def entry(
    request: Request,
    rule_id: str = Form(""),
    points: str = Form(""),
    note: str = Form(...),
    db: DBSession = Depends(get_session),
    parent: User = Depends(require_parent),
):
    child = ledger.get_child(db)
    rules = db.exec(select(Rule).where(Rule.active == True).order_by(Rule.sort_order)).all()  # noqa: E712
    if child is None:
        return render(request, "parent/entry.html", {"child": None, "rules": rules, "error": "还没有孩子的账号"}, status_code=400)

    rid = int(rule_id) if rule_id.isdigit() else None
    rule = db.get(Rule, rid) if rid else None
    if points.strip():
        try:
            val = int(points)
        except ValueError:
            val = None
    else:
        val = rule.points if rule else None
    if val is None or val == 0:
        return render(request, "parent/entry.html", {"child": child, "rules": rules, "error": "分值无效（选规则或手填一个非零整数）"}, status_code=400)
    try:
        ledger.create_manual(db, child.id, val, note, parent.id, rule_id=rule.id if rule else None)
        db.commit()
    except ValueError as e:
        db.rollback()
        return render(request, "parent/entry.html", {"child": child, "rules": rules, "error": str(e)}, status_code=400)
    return RedirectResponse("/parent/ledger", status_code=303)


@router.get("/ledger")
def ledger_page(
    request: Request,
    page: int = 1,
    status: str = "",
    db: DBSession = Depends(get_session),
    parent: User = Depends(require_parent),
):
    page = max(1, page)
    child = ledger.get_child(db)
    conditions = []
    if child is not None:
        conditions.append(PointTransaction.child_id == child.id)
    if status in ("pending", "confirmed", "rejected"):
        conditions.append(PointTransaction.status == status)
    base = select(PointTransaction).where(*conditions) if conditions else select(PointTransaction)
    total = int(db.exec(select(func.count()).select_from(base.subquery())).one())
    stmt = base.order_by(PointTransaction.created_at.desc(), PointTransaction.id.desc())
    stmt = stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    txs = list(db.exec(stmt).all())
    rows = _enrich(db, txs)
    total_pages = max(1, -(-int(total) // PAGE_SIZE))
    return render(
        request,
        "parent/ledger.html",
        {
            "rows": rows,
            "page": page,
            "total_pages": total_pages,
            "status": status,
            "balance": ledger.balance(db, child.id) if child else 0,
            "m": request.query_params.get("m", ""),
        },
    )


# ---- 规则管理 ----

@router.get("/rules")
def rules_page(
    request: Request,
    parent: User = Depends(require_parent),
    db: DBSession = Depends(get_session),
):
    rules = db.exec(select(Rule).order_by(Rule.period, Rule.sort_order, Rule.id)).all()
    return render(request, "parent/rules.html", {"rules": rules, "m": request.query_params.get("m", "")})


@router.post("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    name: str = Form(...),
    icon: str = Form("⭐"),
    points: int = Form(...),
    daily_limit: int = Form(1),
    auto_confirm: str = Form(""),
    active: str = Form(""),
    db: DBSession = Depends(get_session),
    parent: User = Depends(require_parent),
):
    rule = db.get(Rule, rule_id)
    if rule is not None and points != 0:
        rule.name = name.strip() or rule.name
        rule.icon = icon.strip() or "⭐"
        rule.points = points
        rule.daily_limit = max(1, daily_limit)
        rule.auto_confirm = auto_confirm == "on"
        rule.active = active == "on"
        db.add(rule)
        db.commit()
    return RedirectResponse("/parent/rules", status_code=303)


@router.post("/rules")
def add_rule(
    name: str = Form(...),
    icon: str = Form("⭐"),
    points: int = Form(...),
    period: str = Form("daily"),
    category: str = Form("study"),
    daily_limit: int = Form(1),
    db: DBSession = Depends(get_session),
    parent: User = Depends(require_parent),
):
    if name.strip() and points != 0 and period in ("daily", "weekly"):
        rule = Rule(
            name=name.strip(),
            icon=icon.strip() or "⭐",
            points=points,
            period=period,
            category=category if category in ("study", "focus", "honest", "sport") else "study",
            daily_limit=max(1, daily_limit),
            sort_order=99,
        )
        db.add(rule)
        db.commit()
    return RedirectResponse("/parent/rules", status_code=303)


# ---- 设置 ----

@router.get("/settings")
def settings_page(
    request: Request,
    parent: User = Depends(require_parent),
    db: DBSession = Depends(get_session),
):
    child = ledger.get_child(db)
    parents = db.exec(select(User).where(User.role == "parent")).all()
    return render(
        request,
        "parent/settings.html",
        {"parent": parent, "child": child, "parents": parents, "m": request.query_params.get("m", "")},
    )


@router.post("/settings/password")
def change_password(
    old_password: str = Form(...),
    new_password: str = Form(...),
    db: DBSession = Depends(get_session),
    parent: User = Depends(require_parent),
):
    if not verify_secret(old_password, parent.secret_hash):
        return RedirectResponse("/parent/settings?m=" + quote("旧密码不对"), status_code=303)
    if len(new_password) < 6:
        return RedirectResponse("/parent/settings?m=" + quote("新密码至少 6 位"), status_code=303)
    parent.secret_hash = hash_secret(new_password)
    db.add(parent)
    db.commit()
    return RedirectResponse("/parent/settings?m=" + quote("密码已更新"), status_code=303)


@router.post("/settings/pin")
def change_pin(
    new_pin: str = Form(...),
    db: DBSession = Depends(get_session),
    parent: User = Depends(require_parent),
):
    child = ledger.get_child(db)
    new_pin = new_pin.strip()
    if child is None:
        return RedirectResponse("/parent/settings?m=" + quote("还没有孩子的账号"), status_code=303)
    if not (new_pin.isdigit() and len(new_pin) == 4):
        return RedirectResponse("/parent/settings?m=" + quote("PIN 必须是 4 位数字"), status_code=303)
    child.secret_hash = hash_secret(new_pin)
    db.add(child)
    db.commit()
    return RedirectResponse("/parent/settings?m=" + quote("孩子的 PIN 已更新"), status_code=303)


@router.post("/settings/add-parent")
def add_parent(
    name: str = Form(...),
    password: str = Form(...),
    db: DBSession = Depends(get_session),
    parent: User = Depends(require_parent),
):
    name = name.strip()
    exists = db.exec(select(User).where(User.name == name)).first()
    if exists or not name:
        return RedirectResponse("/parent/settings?m=" + quote("用户名已存在或为空"), status_code=303)
    if len(password) < 6:
        return RedirectResponse("/parent/settings?m=" + quote("密码至少 6 位"), status_code=303)
    db.add(User(name=name, role="parent", secret_hash=hash_secret(password)))
    db.commit()
    return RedirectResponse("/parent/settings?m=" + quote("已添加家长账号"), status_code=303)
