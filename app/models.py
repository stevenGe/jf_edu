"""数据模型（SQLModel）。

约定：
- 所有时间均为上海本地墙钟时间（naive datetime），见 config.now_local
- 余额不落库，实时汇总 status="confirmed" 的流水
"""
from datetime import datetime

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel

from .config import now_local


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    role: str = Field(index=True)  # "child" | "parent"
    secret_hash: str  # 孩子=4位PIN，家长=密码，统一 pbkdf2 哈希
    active: bool = True
    created_at: NaiveDatetime = Field(default_factory=now_local)


class Rule(SQLModel, table=True):
    """加分规则（行为目录）。"""
    id: int | None = Field(default=None, primary_key=True)
    name: str
    icon: str = "⭐"
    points: int
    period: str = Field(default="daily", index=True)  # daily | weekly
    category: str = "study"  # study | focus | honest | sport
    auto_confirm: bool = False  # 孩子打卡即入账（用于诚实条款等即时反馈项）
    daily_limit: int = 1  # 每周期最多次数
    active: bool = True
    sort_order: int = 0
    created_at: NaiveDatetime = Field(default_factory=now_local)


class PointTransaction(SQLModel, table=True):
    """积分流水账：每一分加减都有据可查，只能冲正、不能删除。"""
    id: int | None = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="user.id", index=True)
    rule_id: int | None = Field(default=None, foreign_key="rule.id")
    points: int  # 正=获得，负=消耗/冲正
    status: str = Field(default="pending", index=True)  # pending | confirmed | rejected
    source: str = "checkin"  # checkin | parent | reversal | redeem
    note: str = ""
    created_by: int  # 发起人 user_id
    created_at: NaiveDatetime = Field(default_factory=now_local, index=True)
    confirmed_at: NaiveDatetime | None = None
    reversal_of: int | None = Field(default=None, foreign_key="pointtransaction.id")
