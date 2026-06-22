from __future__ import annotations

# 运行模式（D3：测试重置 vs 生产重试隔离）。只管**服务自己写的输出**：收件夹 {order_id}.json + 批量 xlsx。
# 文件生成(SVG/DXF/PNG)是 flower 的，不在此。
#
#   production_retry（默认）—— 写生产目录；批量 xlsx 时间戳命名+不覆盖；{order_id}.json 幂等覆盖（规范文件）。
#   test_reset            —— 写 sandbox 目录、可清旧；**绝不碰生产 outputs/**（计划 §8）。
#
# ⚠️ 设计约束（非猜测）：inbox {order_id}.json 的文件名是 Flower 轮询的键，**不能版本化改名**，
# 否则破坏 Flower 的 *.json 取单约定。故「版本递增」只落在批量 xlsx（与 flower 的生成产物）；
# 收件夹 json 在两种生产模式下都保持幂等覆盖。

from pathlib import Path

from app.config import Settings

PRODUCTION_RETRY = "production_retry"
TEST_RESET = "test_reset"
VALID_MODES = (PRODUCTION_RETRY, TEST_RESET)


def effective_inbox_dir(settings: Settings, mode: str) -> Path:
    return settings.sandbox_inbox_dir if mode == TEST_RESET else settings.inbox_dir


def effective_batches_dir(settings: Settings, mode: str) -> Path:
    return settings.sandbox_batches_dir if mode == TEST_RESET else settings.batches_dir


def clear_dir_files(path: Path) -> int:
    """清掉目录下的文件（保留目录本身、不递归删子目录）。返回删除数。用于 test_reset「清旧」。"""
    path = Path(path)
    if not path.is_dir():
        return 0
    removed = 0
    for child in path.iterdir():
        if child.is_file():
            try:
                child.unlink()
                removed += 1
            except OSError:
                pass
    return removed
