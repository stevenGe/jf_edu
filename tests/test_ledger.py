"""积分流水核心逻辑测试。"""
from datetime import datetime

import pytest
from sqlmodel import Session

from app.database import engine, init_db
from app.models import Rule, User
from app.security import hash_secret
from app.services import ledger


def setup_module():
    init_db()


def make_child(db) -> User:
    child = User(name=f"娃{datetime.now().timestamp()}", role="child", secret_hash=hash_secret("1234"))
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


def make_rule(db, **kw) -> Rule:
    defaults = dict(name="测试任务", icon="🧪", points=2, period="daily",
                    daily_limit=1, auto_confirm=False)
    defaults.update(kw)
    rule = Rule(**defaults)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def test_daily_limit():
    with Session(engine) as db:
        child, rule = make_child(db), make_rule(db, daily_limit=3, points=1)
        for _ in range(3):
            ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 2, 19, 0))
        with pytest.raises(ValueError):
            ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 2, 20, 0))
        # 第二天恢复
        ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 3, 19, 0))


def test_confirm_and_balance():
    with Session(engine) as db:
        child, rule = make_child(db), make_rule(db, points=3)
        tx = ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 2, 19, 0))
        assert tx.status == "pending"
        assert ledger.balance(db, child.id) == 0
        ledger.confirm_tx(db, tx)
        assert ledger.balance(db, child.id) == 3


def test_reject_not_counted():
    with Session(engine) as db:
        child, rule = make_child(db), make_rule(db)
        tx = ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 2, 19, 0))
        ledger.reject_tx(db, tx)
        assert ledger.balance(db, child.id) == 0


def test_reverse_net_zero_and_double_reverse_blocked():
    with Session(engine) as db:
        child, rule = make_child(db), make_rule(db, points=3)
        tx = ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 2, 19, 0))
        ledger.confirm_tx(db, tx)
        parent = User(name="测试家长", role="parent", secret_hash=hash_secret("x12345"))
        db.add(parent); db.commit(); db.refresh(parent)
        rev = ledger.reverse_tx(db, tx, parent.id, at=datetime(2025, 6, 2, 21, 0))
        assert rev.points == -3 and rev.status == "confirmed"
        assert ledger.balance(db, child.id) == 0  # 净额归零
        assert tx.id in ledger.reversed_ids(db, [tx.id])
        with pytest.raises(ValueError):
            ledger.reverse_tx(db, rev, parent.id)  # 冲正记录不能再冲正


def test_auto_confirm_checkin():
    with Session(engine) as db:
        child, rule = make_child(db), make_rule(db, auto_confirm=True, points=1)
        tx = ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 2, 19, 0))
        assert tx.status == "confirmed"
        assert ledger.balance(db, child.id) == 1


def test_weekly_period_bounds():
    with Session(engine) as db:
        child, rule = make_child(db), make_rule(db, period="weekly", daily_limit=1)
        # 6月2日是周一
        ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 2, 10, 0))
        with pytest.raises(ValueError):
            ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 5, 10, 0))  # 同一周
        ledger.create_checkin(db, child.id, rule, child.id, at=datetime(2025, 6, 9, 10, 0))  # 下周一


def test_manual_requires_note():
    with Session(engine) as db:
        child = make_child(db)
        parent = User(name="备注测试家长", role="parent", secret_hash=hash_secret("x12345"))
        db.add(parent); db.commit(); db.refresh(parent)
        with pytest.raises(ValueError):
            ledger.create_manual(db, child.id, 5, "  ", parent.id)
        ledger.create_manual(db, child.id, -1, "忘带作业本", parent.id)
        assert ledger.balance(db, child.id) == -1


def test_week_bounds_monday():
    start, end = ledger.week_bounds(datetime(2025, 6, 5).date())  # 周四
    assert start == datetime(2025, 6, 2, 0, 0)
    assert end == datetime(2025, 6, 9, 0, 0)
