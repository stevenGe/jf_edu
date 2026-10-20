# 🏡 积分小屋 —— 家庭学习积分系统

给三年级孩子的学习积分系统：孩子自己打卡赚分，家长晚上几分钟确认，每一分都有流水可查。

设计文档见 `docs/`：

- `docs/01-现状分析与积分设计原则.md` —— 业务背景与积分规则
- `docs/02-技术方案与产品功能设计.md` —— 技术选型与里程碑

## 技术栈

FastAPI + Jinja2（服务端渲染）+ SQLModel + SQLite(WAL)，纯 Python，无前端构建链，无外部 CDN 依赖。

## 快速开始（本机试用）

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
python -m app.init_db              # 初始化数据库，会打印初始账号密码
uvicorn app.main:app --reload --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。

- 孩子端：4 位数字 PIN
- 家长端：用户名 + 密码

> 初始密码是随机生成的，打印在 `init_db` 的输出里。**上线后请立刻在【家长端 → 设置】里修改。**
> 也可以在初始化时指定：`CHILD_NAME=小明 CHILD_PIN=1234 PARENT_NAME=爸爸 PARENT_PASSWORD=yourpass python -m app.init_db`

## 部署到云服务器（Linux）

### 1. 安装并初始化

```bash
git clone <你的仓库> /opt/jfedu && cd /opt/jfedu
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m app.init_db
```

### 2. systemd 服务

`/etc/systemd/system/jfedu.service`：

```ini
[Unit]
Description=JF Edu Points
After=network.target

[Service]
WorkingDirectory=/opt/jfedu
ExecStart=/opt/jfedu/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8300
Restart=always
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now jfedu
```

### 3. 反向代理（强烈建议 HTTPS）

Caddy 示例（自动申请证书）：

```
points.example.com {
    reverse_proxy 127.0.0.1:8300
}
```

### 4. 数据备份（cron）

```cron
30 3 * * * sqlite3 /opt/jfedu/data/jf_edu.db ".backup /opt/jfedu/backup/jf_$(date +\%F).db"
```

## 常用维护命令

```bash
.venv/bin/python -m app.init_db --add-parent 妈妈 --password abc12345   # 添加家长
.venv/bin/python -m app.init_db --set-secret 小明 --secret 5678         # 重置 PIN/密码
.venv/bin/python -m pytest                                             # 跑测试
```

## 角色与核心流程

```
孩子：今日打卡（每日/每周任务）→ 待确认 → 我的记录
家长：待确认列表批量确认/驳回 → 手动记账 → 流水（可冲正）→ 规则管理 → 设置
```

积分规则说明（种子数据）：

| 行为 | 分值 | 说明 |
|---|---|---|
| 独立完成学校作业 | +2 | 家长确认 |
| 专注番茄钟（20 分钟） | +1 ×3/日 | 打卡即入账 |
| 给家长讲一道今天学的题 | +3 | 家长确认 |
| 错题订正并讲出错因 | +2 | 家长确认 |
| 主动说"我不会 / 我抄了" | +1 | 打卡即入账（诚实条款） |
| 本周作业全部独立完成 | +5/周 | 家长确认 |
| 计算正确率超过上周 | +3/周 | 家长确认 |
| 体能课认真投入 | +2/周 | 家长确认 |
| 家庭会议好建议被采纳 | +1/周 | 家长确认 |

## 设计要点（详见 docs）

- **流水不可删**：家长录错只能"冲正"（追加等额反向记录），对孩子的信任比数据整洁重要
- **余额实时汇总**：不单独存余额字段，永不对不上账
- **诚实安全条款**：主动承认不会/抄袭反而加分，从源头降低抄袭动机
- **克制扣分**：本系统是赚分系统，不是监控系统

## 路线图

- [x] M1：登录、打卡、确认、流水余额、规则管理、设置
- [ ] M2：兑换商店、周项自动结算提醒、老师周反馈、周报
- [ ] M3：趋势图表、连续徽章、PWA 加主屏
- [ ] M4：导出、多孩子支持（按需）

**M1 上线后建议先用两周再开发 M2**——规则数字需要根据真实使用调整。
