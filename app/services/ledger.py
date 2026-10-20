"""积分流水核心逻辑：打卡、确认、驳回、冲正、余额。"""
from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from ..config import now_local
from ..models import PointTransaction, Rule, User

ACTIVE_STATUSES = ("pending", "confirmed")
STATUS_LABELS = {"pending": "待确认", "confirmed": "已入账", "rejected": "未通过"}
SOURCE_LABELS = {"checkin": "打卡", "parent": "家长", "reversal": "冲正", "redeem": "兑换"}


# ---- 时间周期 ----

def day_bounds(d: date) -> tuple[datetime, datetime]:
    return datetime.combine(d, time.min), datetime.combine(d + timedelta(days=1), time.min)


def week_bounds(d: date) -> tuple[datetime, datetime]:
    """周一 0 点 ~ 下周一 0 点（上海本地时间）。"""
    monday = d - timedelta(days=d.weekday())
    start = datetime.combine(monday, time.min)
    end = datetime.combine(monday + timedelta(days=7), time.min)
    return start, end


def period_bounds(period: str, d: date) -> tuple[datetime, datetime]:
    return week_bounds(d) if period == "weekly" else day_bounds(d)


# ---- 查询 ----

def balance(session: Session, child_id: int) -> int:
    stmt = select(func.coalesce(func.sum(PointTransaction.points), 0)).where(
        PointTransaction.child_id == child_id,
        PointTransaction.status == "confirmed",
    )
    return int(session.exec(stmt).one())


def sum_confirmed_between(session: Session, child_id: int, start: datetime, end: datetime) -> int:
    stmt = select(func.coalesce(func.sum(PointTransaction.points), 0)).where(
        PointTransaction.child_id == child_id,
        PointTransaction.status == "confirmed",
        PointTransaction.created_at >= start,
        PointTransaction.created_at < end,
    )
    return int(session.exec(stmt).one())


def period_stats(session: Session, child_id: int, rule: Rule, at: datetime | None = None) -> dict:
    """某规则在当前周期内的打卡统计（供孩子端渲染）。"""
    at = at or now_local()
    start, end = period_bounds(rule.period, at.date())

    def _count(statuses: tuple[str, ...]) -> int:
        stmt = (
            select(func.count())
            .select_from(PointTransaction)
            .where(
                PointTransaction.child_id == child_id,
                PointTransaction.rule_id == rule.id,
                PointTransaction.created_at >= start,
                PointTransaction.created_at < end,
                PointTransaction.status.in_(statuses),
            )
        )
        return int(session.exec(stmt).one())

    return {
        "total": _count(ACTIVE_STATUSES),
        "pending": _count(("pending",)),
        "confirmed": _count(("confirmed",)),
        "limit": max(1, rule.daily_limit),
    }


def pending_transactions(session: Session) -> list[PointTransaction]:
    stmt = (
        select(PointTransaction)
        .where(PointTransaction.status == "pending")
        .order_by(PointTransaction.created_at.desc())
    )
    return list(session.exec(stmt).all())


def reversed_ids(session: Session, ids: list[int]) -> set[int]:
    """哪些流水 id 已被冲正（存在指向它们的冲正记录）。"""
    ids = [i for i in ids if i]
    if not ids:
        return set()
    stmt = select(PointTransaction.reversal_of).where(
        PointTransaction.reversal_of.in_(ids),
        PointTransaction.status == "confirmed",
    )
    return {i for i in session.exec(stmt).all() if i is not None}


def get_child(session: Session) -> User | None:
    stmt = (
        select(User)
        .where(User.role == "child", User.active == True)  # noqa: E712
        .limit(1)
    )
    return session.exec(stmt).first()


# ---- 写操作 ----

def create_checkin(
    session: Session, child_id: int, rule: Rule, by_id: int, at: datetime | None = None
) -> PointTransaction:
    """孩子打卡：生成 pending 流水（auto_confirm 规则直接 confirmed）。"""
    at = at or now_local()
    if not rule.active:
        raise ValueError("这个任务暂时下线了")
    stats = period_stats(session, child_id, rule, at)
    if stats["total"] >= stats["limit"]:
        raise ValueError("这个任务的次数已经用完啦")
    tx = PointTransaction(
        child_id=child_id,
        rule_id=rule.id,
        points=rule.points,
        status="confirmed" if rule.auto_confirm else "pending",
        source="checkin",
        note="",
        created_by=by_id,
        created_at=at,
        confirmed_at=at if rule.auto_confirm else None,
    )
    session.add(tx)
    return tx


def confirm_tx(session: Session, tx: PointTransaction, at: datetime | None = None) -> None:
    if tx.status != "pending":
        raise ValueError("只有待确认的记录才能确认")
    tx.status = "confirmed"
    tx.confirmed_at = at or now_local()


def reject_tx(session: Session, tx: PointTransaction) -> None:
    if tx.status != "pending":
        raise ValueError("只有待确认的记录才能驳回")
    tx.status = "rejected"


def reverse_tx(
    session: Session, tx: PointTransaction, by_id: int, note: str = "", at: datetime | None = None
) -> PointTransaction:
    """冲正：不动原记录，追加一条等额反向的 confirmed 流水，净额归零。"""
    if tx.status != "confirmed":
        raise ValueError("只能冲正已确认的记录")
    if tx.reversal_of is not None:
        raise ValueError("冲正记录不能再次冲正")
    at = at or now_local()
    reversal = PointTransaction(
        child_id=tx.child_id,
        rule_id=tx.rule_id,
        points=-tx.points,
        status="confirmed",
        source="reversal",
        note=note.strip() or f"冲正 #{tx.id}",
        created_by=by_id,
        created_at=at,
        confirmed_at=at,
        reversal_of=tx.id,
    )
    session.add(reversal)
    return reversal


def create_manual(
    session: Session,
    child_id: int,
    points: int,
    note: str,
    by_id: int,
    rule_id: int | None = None,
    source: str = "parent",
    at: datetime | None = None,
) -> PointTransaction:
    """家长手动记账（直接 confirmed）。"""
    if not note.strip():
        raise ValueError("备注必填")
    at = at or now_local()
    tx = PointTransaction(
        child_id=child_id,
        rule_id=rule_id,
        points=int(points),
        status="confirmed",
        source=source,
        note=note.strip(),
        created_by=by_id,
        created_at=at,
        confirmed_at=at,
    )
    session.add(tx)
    return tx
