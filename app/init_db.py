"""初始化数据库与种子数据。

用法：
    python -m app.init_db                          # 初始化（仅空库时写入种子账号与规则）
    CHILD_NAME=小明 CHILD_PIN=1234 python -m app.init_db
    python -m app.init_db --add-parent 妈妈 --password abc12345
    python -m app.init_db --set-secret 小明 --secret 5678     # 改 PIN/密码
"""
import argparse
import os
import secrets
import sys

from sqlmodel import Session, select

from .database import engine, init_db
from .models import Rule, User
from .security import hash_secret

SEED_RULES: list[dict] = [
    # 每日
    dict(name="独立完成学校作业", icon="📝", points=2, period="daily", category="study",
         auto_confirm=False, daily_limit=1, sort_order=10),
    dict(name="专注番茄钟（20 分钟）", icon="⏰", points=1, period="daily", category="focus",
         auto_confirm=True, daily_limit=3, sort_order=20),
    dict(name="给家长讲一道今天学的题", icon="🗣️", points=3, period="daily", category="study",
         auto_confirm=False, daily_limit=1, sort_order=30),
    dict(name="错题订正并讲出错因", icon="🔍", points=2, period="daily", category="study",
         auto_confirm=False, daily_limit=1, sort_order=40),
    dict(name='主动说"我不会 / 我抄了"', icon="💬", points=1, period="daily", category="honest",
         auto_confirm=True, daily_limit=1, sort_order=50),
    # 每周
    dict(name="本周作业全部独立完成", icon="🏆", points=5, period="weekly", category="study",
         auto_confirm=False, daily_limit=1, sort_order=60),
    dict(name="计算正确率超过上周", icon="📈", points=3, period="weekly", category="study",
         auto_confirm=False, daily_limit=1, sort_order=70),
    dict(name="体能课认真投入", icon="🏃", points=2, period="weekly", category="sport",
         auto_confirm=False, daily_limit=1, sort_order=80),
    dict(name="家庭会议好建议被采纳", icon="🤝", points=1, period="weekly", category="honest",
         auto_confirm=False, daily_limit=1, sort_order=90),
]


def seed(session: Session) -> list[str]:
    """空库时写入种子账号与规则，返回要打印的提示信息。"""
    infos: list[str] = []
    if session.exec(select(User).limit(1)).first() is not None:
        return infos  # 已有账号，跳过种子

    child_name = os.environ.get("CHILD_NAME", "孩子")
    child_pin = os.environ.get("CHILD_PIN") or str(secrets.randbelow(9000) + 1000)
    parent_name = os.environ.get("PARENT_NAME", "爸爸")
    parent_pw = os.environ.get("PARENT_PASSWORD") or secrets.token_urlsafe(6)

    session.add(User(name=child_name, role="child", secret_hash=hash_secret(child_pin)))
    session.add(User(name=parent_name, role="parent", secret_hash=hash_secret(parent_pw)))
    session.add_all(Rule(**r) for r in SEED_RULES)
    session.commit()

    infos.append("种子账号（请尽快在【家长端-设置】里修改）：")
    infos.append(f"  孩子  {child_name}  PIN: {child_pin}")
    infos.append(f"  家长  {parent_name}  密码: {parent_pw}")
    return infos


def add_parent(session: Session, name: str, password: str) -> str:
    if not name or len(password) < 6:
        return "名字不能为空，密码至少 6 位"
    if session.exec(select(User).where(User.name == name)).first() is not None:
        return f"用户名 {name} 已存在"
    session.add(User(name=name, role="parent", secret_hash=hash_secret(password)))
    session.commit()
    return f"已添加家长账号：{name}"


def set_secret(session: Session, name: str, secret: str) -> str:
    user = session.exec(select(User).where(User.name == name)).first()
    if user is None:
        return f"找不到用户：{name}"
    if user.role == "child" and not (secret.isdigit() and len(secret) == 4):
        return "孩子的 PIN 必须是 4 位数字"
    if user.role == "parent" and len(secret) < 6:
        return "家长密码至少 6 位"
    user.secret_hash = hash_secret(secret)
    session.add(user)
    session.commit()
    return f"已更新 {name} 的{'PIN' if user.role == 'child' else '密码'}"


def main() -> int:
    parser = argparse.ArgumentParser(description="积分小屋 - 初始化工具")
    parser.add_argument("--add-parent", metavar="NAME", help="新增家长账号（配合 --password）")
    parser.add_argument("--password", default="", help="新增家长的密码")
    parser.add_argument("--set-secret", metavar="NAME", help="重置某用户的 PIN/密码（配合 --secret）")
    parser.add_argument("--secret", default="", help="新的 PIN/密码")
    args = parser.parse_args()

    init_db()
    with Session(engine) as session:
        if args.add_parent:
            print(add_parent(session, args.add_parent.strip(), args.password))
        elif args.set_secret:
            if not args.secret:
                print("缺少 --secret 参数")
                return 1
            print(set_secret(session, args.set_secret.strip(), args.secret))
        else:
            infos = seed(session)
            if infos:
                print("\n".join(infos))
            else:
                print("数据库已有账号，跳过种子数据。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
