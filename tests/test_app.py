"""路由冒烟测试：登录 → 孩子打卡 → 家长确认 → 流水。"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.database import engine, init_db
from app.main import app
from app.models import Rule, User
from app.security import hash_secret


@pytest.fixture(scope="module")
def seeded():
    init_db()
    with Session(engine) as db:
        child = User(name="冒烟娃", role="child", secret_hash=hash_secret("2468"))
        parent = User(name="冒烟爸", role="parent", secret_hash=hash_secret("test123456"))
        rule = Rule(name="冒烟任务", icon="🧪", points=2, period="daily", daily_limit=1)
        db.add(child); db.add(parent); db.add(rule)
        db.commit()
        db.refresh(child); db.refresh(parent); db.refresh(rule)
        yield {"child": child, "parent": parent, "rule": rule}


def login(client, role, **fields):
    r = client.post("/login", data={"role": role, **fields}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r


def test_full_flow(seeded):
    with TestClient(app) as client:
        # 未登录 → 跳登录页
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"

        # 错误 PIN
        r = client.post("/login", data={"role": "child", "pin": "0000"})
        assert r.status_code == 401

        # 孩子登录并打卡
        login(client, "child", pin="2468")
        r = client.get("/")
        assert "冒烟任务" in r.text
        import re
        token = re.search(r'name="_csrf" value="([^"]+)"', r.text).group(1)
        r = client.post(f"/checkin/{seeded['rule'].id}",
                        data={"_csrf": token}, follow_redirects=False)
        assert r.status_code == 303

        # 孩子访问家长端会被弹回
        r = client.get("/parent", follow_redirects=False)
        assert r.status_code == 303

        # 家长登录（换会话）
        client.cookies.clear()
        login(client, "parent", name="冒烟爸", password="test123456")
        r = client.get("/parent")
        assert "待确认" in r.text
        assert "冒烟任务" in r.text

        # 确认第一条待确认流水
        m = re.search(r'/parent/tx/(\d+)/confirm', r.text)
        assert m, "页面上应出现确认按钮"
        # 取 CSRF token
        token = re.search(r'name="_csrf" value="([^"]+)"', r.text).group(1)
        r = client.post(f"/parent/tx/{m.group(1)}/confirm",
                        data={"_csrf": token}, follow_redirects=False)
        assert r.status_code == 303

        # 流水页应显示已入账
        r = client.get("/parent/ledger")
        assert "已入账" in r.text

        # 登出
        r = client.post("/logout", follow_redirects=False)
        assert r.status_code == 303


def test_csrf_rejected(seeded):
    with TestClient(app) as client:
        login(client, "child", pin="2468")
        r = client.post(f"/checkin/{seeded['rule'].id}",
                        data={"_csrf": "garbage"}, follow_redirects=False)
        assert r.status_code == 400
