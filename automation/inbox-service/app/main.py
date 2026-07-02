from __future__ import annotations

import threading

from app.factory import create_app

# uvicorn 入口：`uvicorn app.main:app --host 127.0.0.1 --port 8770`
app = create_app()

# 启动报告监听后台线程：轮询 outputs/reports/*-report.xlsx 回写订单状态。
# 仅生产入口触发；测试用 app.factory.create_app 不会起线程。
threading.Thread(target=app.state.report_watcher.run_forever, daemon=True).start()

# 启动退款重抓后台线程：周期性算「该重抓退款状态」的在产订单（扩展拉 /inbox/refund/pending 逐单重抓）。
threading.Thread(target=app.state.refund_scheduler.run_forever, daemon=True).start()
