"""GUI 端到端验收订单工厂（跑在 inbox-service venv，走**正式模型 + 正式 repository 层**）。

非 mock：用真实 ``Order`` SQLAlchemy 模型 + ``upsert_order`` + ``bind_order_template`` 把一条验收
订单持久化进指定 SQLite，绑定 GIMP 模板，再把 ``order.to_dict()`` 打到 JSON。flower 桌面端读取这份
to_dict 即拿到 template_id/version/sha256。供 tools/gimp_production_e2e.py 跨 venv 调用。

用法：python tools/make_acceptance_order.py <db_path> <order_id> <template_id> <version> <sha256> <out_json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 让 `app` 包可导入

from app.db import Base, make_engine  # noqa: E402
from app.db import Session as _SessionType  # noqa: E402,F401  (确保 db 模块完全加载)
from sqlalchemy.orm import Session  # noqa: E402
from app import models  # noqa: E402,F401  注册所有表
from app.repository import bind_order_template, upsert_order  # noqa: E402
from app.schemas import OrderPayload  # noqa: E402


def main() -> None:
    db_path, order_id, template_id, version, sha, out_json = sys.argv[1:7]
    engine = make_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)  # 验收用专用库；表结构 == 正式模型（迁移另由 alembic 验证）
    with Session(engine) as session:
        payload = OrderPayload(schema_version="1", order_id=order_id,
                               remark="GUI e2e acceptance order", shop="e2e-shop")
        order, *_ = upsert_order(session, payload, raw_json=payload.model_dump_json())
        bound = bind_order_template(session, order_id, template_id=template_id,
                                    template_version=version, template_sha256=sha)
        session.commit()
        data = bound.to_dict()
    Path(out_json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # 回读验证：重新开 session 从库里取，证明确实持久化（非内存 dict）。
    with Session(engine) as session:
        reloaded = session.get(models.Order, order_id)
        assert reloaded is not None and reloaded.template_id == template_id
        assert reloaded.template_binding_status == "bound"
    print(json.dumps({"order_id": order_id, "template_id": data.get("template_id"),
                      "template_version": data.get("template_version"),
                      "template_sha256": data.get("template_sha256"),
                      "template_binding_status": data.get("template_binding_status"),
                      "persisted_reload_ok": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
