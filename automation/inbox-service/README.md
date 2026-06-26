# Flower 本地收单服务（inbox-service）

店小秘 → Flower 自动取单的本地伴随服务（automation 一期，独立小服务）。Chrome 扩展把抓到的订单
POST 到本服务；服务校验、去重、记录状态，并把订单原子写成 `{order_id}.json` 投进 Flower 的收件夹。

- 不挂靠已暂缓 web 的 `services/api`，独立运行、独立 venv。
- 数据合同：`../contracts/order.schema.json`（三方共用）。

## 安装（独立 venv）

```powershell
cd automation\inbox-service
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn pydantic sqlalchemy alembic openpyxl httpx pytest
```

## 运行

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8770
```

环境变量（可选）：`FLOWER_INBOX_DIR`（收件夹，默认 `<flower>/outputs/inbox`）、`FLOWER_INBOX_DB`、`FLOWER_INBOX_PORT`（默认 8770）。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 迁移（Alembic）

建表既可由服务启动时 `init_db`（create_all）完成，也可用 Alembic：

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## 端点

- `POST /inbox/orders` — 收单：校验 → 去重 upsert → 原子写收件夹。
- `GET /inbox/orders` / `GET /inbox/orders/{order_id}` — 状态查询。
- `GET /healthz` — 探活（回显收件夹/DB 路径）。
- `POST /inbox/batch/export`（M4）— 把池中订单导出成店小秘格式 xlsx 供 Flower 批量导入。
