"""共享提示词库（SQLite）。

「提示词」原本是挂在每个产品上的一整套数据（reference_fields / prompt_template /
background_prompt / template_version / field_seq_max）。这里把它们搬进 flower 内的
SQLite 共享库 ``prompts.db``：产品改为按 ``prompt_set_id`` 引用一个 set，纯共享、不再
持有副本。下游解析链路（resolve_prompt_template）零改动——只把「fields 来自
product.reference_fields」换成「来自本库按 set_id 载出的 set.reference_fields」。

关键不变量见模块内各函数注释；尤其：迁移必须**原样保留每个 field 的 uuid**，否则
prompt_template 里 ``{{field:uuid}}`` 全部失效。
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

import config_store
from prompt_references import (
    ReferenceField,
    default_prompt_template,
    now_iso,
    reference_fields_from_legacy,
)


def _default_db_path() -> Path:
    """prompts.db 与主配置同目录（取 DEFAULT_CONFIG_PATH 的父目录）。"""
    return Path(config_store.DEFAULT_CONFIG_PATH).parent / "prompts.db"


# 序号原子分配的进程内锁。等价旧 create_product_reference_field_in_file 的
# _CONFIG_WRITE_LOCK 语义：保证同进程并发 allocate 不撞号。
_ALLOC_LOCK = threading.RLock()


@dataclass(frozen=True)
class PromptSet:
    """一套共享提示词。reference_fields 含全部（enabled/deleted 由上层 active_reference_fields 过滤）。"""

    id: str
    name: str
    prompt_template: str
    background_prompt: str
    template_version: int
    field_seq_max: int
    reference_fields: tuple[ReferenceField, ...]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompt_sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prompt_template TEXT NOT NULL DEFAULT '',
    background_prompt TEXT NOT NULL DEFAULT '',
    template_version INTEGER NOT NULL DEFAULT 1,
    field_seq_max INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS reference_fields (
    id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL REFERENCES prompt_sets(id) ON DELETE CASCADE,
    sequence_number INTEGER NOT NULL,
    reference_name TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    field_type TEXT NOT NULL DEFAULT '',
    legacy_key TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reference_fields_set ON reference_fields(set_id);
"""


def _connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """打开连接并启用外键 + 建表（幂等）。"""
    path = Path(db_path) if db_path is not None else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """显式建表（建表已在 _connect 中幂等执行，单独暴露便于初始化/测试）。"""
    conn = _connect(db_path)
    try:
        conn.commit()
    finally:
        conn.close()


def _row_to_field(row: sqlite3.Row) -> ReferenceField:
    return ReferenceField(
        id=row["id"],
        scope_id=row["set_id"],
        sequence_number=int(row["sequence_number"]),
        reference_name=row["reference_name"],
        prompt=row["prompt"] or "",
        sort_order=int(row["sort_order"]),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        deleted_at=row["deleted_at"] or "",
        field_type=row["field_type"] or "",
        legacy_key=row["legacy_key"] or "",
    )


def _insert_fields(conn: sqlite3.Connection, set_id: str, fields: Iterable[ReferenceField]) -> None:
    """把 fields 写入 reference_fields。set_id 取 set，field.scope_id 被忽略（统一为 set_id）。"""
    conn.executemany(
        """
        INSERT INTO reference_fields (
            id, set_id, sequence_number, reference_name, prompt, sort_order,
            enabled, field_type, legacy_key, created_at, updated_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                field.id,
                set_id,
                field.sequence_number,
                field.reference_name,
                field.prompt or "",
                field.sort_order,
                1 if field.enabled else 0,
                field.field_type or "",
                field.legacy_key or "",
                field.created_at or "",
                field.updated_at or "",
                field.deleted_at or "",
            )
            for field in fields
        ],
    )


def load_prompt_set(set_id: str, db_path: Path | str | None = None) -> PromptSet | None:
    """按 set_id 载出整套（含全部 field，不过滤 enabled/deleted）。不存在返回 None。"""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM prompt_sets WHERE id = ?", (set_id,)).fetchone()
        if row is None:
            return None
        field_rows = conn.execute(
            "SELECT * FROM reference_fields WHERE set_id = ? ORDER BY sort_order, sequence_number",
            (set_id,),
        ).fetchall()
        return PromptSet(
            id=row["id"],
            name=row["name"],
            prompt_template=row["prompt_template"] or "",
            background_prompt=row["background_prompt"] or "",
            template_version=int(row["template_version"]),
            field_seq_max=int(row["field_seq_max"]),
            reference_fields=tuple(_row_to_field(r) for r in field_rows),
        )
    finally:
        conn.close()


def list_prompt_sets(db_path: Path | str | None = None) -> tuple[tuple[str, str], ...]:
    """返回 (id, name) 列表，供选择器使用。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT id, name FROM prompt_sets ORDER BY created_at, name").fetchall()
        return tuple((row["id"], row["name"]) for row in rows)
    finally:
        conn.close()


def create_prompt_set(
    name: str,
    *,
    prompt_template: str = "",
    background_prompt: str = "",
    template_version: int = 1,
    set_id: str | None = None,
    fields: Iterable[ReferenceField] = (),
    db_path: Path | str | None = None,
) -> str:
    """新建一套提示词，返回 set_id。field_seq_max 由传入 fields 的最大 sequence_number 推出。"""
    new_id = set_id or str(uuid.uuid4())
    field_tuple = tuple(fields)
    field_seq_max = max((field.sequence_number for field in field_tuple), default=0)
    timestamp = now_iso()
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO prompt_sets (
                id, name, prompt_template, background_prompt,
                template_version, field_seq_max, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id,
                name,
                prompt_template or "",
                background_prompt or "",
                int(template_version),
                field_seq_max,
                timestamp,
                timestamp,
            ),
        )
        _insert_fields(conn, new_id, field_tuple)
        conn.commit()
        return new_id
    finally:
        conn.close()


def replace_prompt_set_fields(
    set_id: str,
    reference_fields: Iterable[ReferenceField],
    *,
    prompt_template: str | None = None,
    background_prompt: str | None = None,
    template_version: int | None = None,
    db_path: Path | str | None = None,
) -> None:
    """原子整体替换一套的字段（等价旧 with_product_reference_fields）。

    在单个事务里删旧 field、插新 field 并按需更新 template/background/version；
    field_seq_max 取「现存值」与「新 fields 最大 sequence_number」的较大者，绝不回退。
    """
    field_tuple = tuple(reference_fields)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT prompt_template, background_prompt, template_version, field_seq_max "
            "FROM prompt_sets WHERE id = ?",
            (set_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"提示词套不存在：{set_id!r}")
        new_template = row["prompt_template"] if prompt_template is None else prompt_template
        new_background = row["background_prompt"] if background_prompt is None else background_prompt
        new_version = row["template_version"] if template_version is None else int(template_version)
        new_seq_max = max(
            int(row["field_seq_max"]),
            *(field.sequence_number for field in field_tuple),
            0,
        )
        conn.execute("DELETE FROM reference_fields WHERE set_id = ?", (set_id,))
        _insert_fields(conn, set_id, field_tuple)
        conn.execute(
            "UPDATE prompt_sets SET prompt_template = ?, background_prompt = ?, "
            "template_version = ?, field_seq_max = ?, updated_at = ? WHERE id = ?",
            (
                new_template or "",
                new_background or "",
                new_version,
                new_seq_max,
                now_iso(),
                set_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def allocate_field_in_set(
    set_id: str,
    reference_name: str,
    *,
    prompt: str = "",
    field_type: str = "",
    legacy_key: str = "",
    db_path: Path | str | None = None,
) -> tuple[ReferenceField, int]:
    """在一个事务里原子分配序号（new_seq = field_seq_max + 1）并回写，保证并发不撞号。

    返回 (新建的 ReferenceField, 新的 field_seq_max)。对应旧
    create_product_reference_field_in_file 的 _CONFIG_WRITE_LOCK 语义。
    """
    with _ALLOC_LOCK:
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT field_seq_max FROM prompt_sets WHERE id = ?", (set_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"提示词套不存在：{set_id!r}")
            new_seq = int(row["field_seq_max"]) + 1
            timestamp = now_iso()
            field = ReferenceField(
                id=str(uuid.uuid4()),
                scope_id=set_id,
                sequence_number=new_seq,
                reference_name=reference_name,
                prompt=prompt or "",
                sort_order=new_seq,
                enabled=True,
                created_at=timestamp,
                updated_at=timestamp,
                deleted_at="",
                field_type=field_type or "",
                legacy_key=legacy_key or "",
            )
            _insert_fields(conn, set_id, (field,))
            conn.execute(
                "UPDATE prompt_sets SET field_seq_max = ?, updated_at = ? WHERE id = ?",
                (new_seq, timestamp, set_id),
            )
            conn.commit()
            return field, new_seq
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ===== 迁移：把产品原始 JSON payload 重建为一套 prompt_set =====


def _optional_str(payload: dict[str, Any], key: str, default: str = "") -> str:
    if key not in payload:
        return default
    value = payload.get(key)
    return value if isinstance(value, str) else default


def _int_or(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fields_from_payload(value: Any, set_id: str) -> tuple[ReferenceField, ...]:
    """重建 reference_fields（保 id）。复用 config_store._reference_fields_from_payload 的语义。

    scope_id 一律置为 set_id；id 原样保留（缺 id 的项跳过，与旧逻辑一致）。
    """
    if not isinstance(value, list):
        return ()
    fields: list[ReferenceField] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        field_id = _optional_str(item, "id", "")
        if not field_id:
            continue
        sequence = _int_or(item.get("sequence_number"), 0)
        if sequence <= 0:
            continue
        fields.append(
            ReferenceField(
                id=field_id,
                scope_id=set_id,
                sequence_number=sequence,
                reference_name=_optional_str(item, "reference_name", "") or f"字段{sequence}",
                prompt=_optional_str(item, "prompt", ""),
                sort_order=_int_or(item.get("sort_order"), sequence),
                enabled=bool(item.get("enabled", True)),
                created_at=_optional_str(item, "created_at", ""),
                updated_at=_optional_str(item, "updated_at", ""),
                deleted_at=_optional_str(item, "deleted_at", ""),
                field_type=_optional_str(item, "field_type", "文本") or "文本",
                legacy_key=_optional_str(item, "legacy_key", ""),
            )
        )
    return tuple(sorted(fields, key=lambda field: (field.sort_order, field.sequence_number)))


def migrate_product_payload(
    payload: dict[str, Any],
    *,
    set_id: str | None = None,
    name: str | None = None,
    db_path: Path | str | None = None,
) -> str:
    """从一个产品的原始 JSON payload 重建提示词、建一套 set，返回 set_id（保 field id）。

    payload 含 reference_fields / extraction_prompt / prompt_template /
    background_prompt / field_seq_max / template_version。重建逻辑与
    config_store._product_from_payload 对齐：
      - 优先用 reference_fields（保 id）；为空则从 extraction_prompt 走旧版解析。
      - prompt_template 缺失且有字段时，用 default_prompt_template 合成。
    """
    background_prompt = _optional_str(payload, "background_prompt", "")
    extraction_prompt = _optional_str(payload, "extraction_prompt", "")
    new_id = set_id or str(uuid.uuid4())

    reference_fields = _fields_from_payload(payload.get("reference_fields"), new_id)
    if not reference_fields:
        reference_fields = reference_fields_from_legacy(extraction_prompt, scope_id=new_id)

    field_seq_max = _int_or(
        payload.get("field_seq_max"),
        max((field.sequence_number for field in reference_fields), default=0),
    )
    field_seq_max = max(field_seq_max, *(field.sequence_number for field in reference_fields), 0)

    prompt_template = _optional_str(payload, "prompt_template", "")
    if not prompt_template and reference_fields:
        prompt_template = default_prompt_template(reference_fields, background_prompt)

    template_version = _int_or(payload.get("template_version"), 1)
    set_name = name if name is not None else (_optional_str(payload, "name", "") or new_id)

    timestamp = now_iso()
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO prompt_sets (
                id, name, prompt_template, background_prompt,
                template_version, field_seq_max, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id,
                set_name,
                prompt_template or "",
                background_prompt or "",
                template_version,
                field_seq_max,
                timestamp,
                timestamp,
            ),
        )
        _insert_fields(conn, new_id, reference_fields)
        conn.commit()
        return new_id
    finally:
        conn.close()
