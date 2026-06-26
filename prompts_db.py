"""共享提示词库（SQLite）—— 字段「定义 / 值」分离模型。

数据模型（2026-06-26 重构）：
- ``field_definitions``（**全局唯一**）：字段的身份 + 显示名 + 类型 + 全局默认内容。``id``=uuid，
  **仅内部用、绝不展示给用户**；同名(归一化)+同类型在全库唯一（应用层 get-or-create 保证）。
- ``prompt_sets``（**一产品可多套**）：一套 = 某产品的一份字段内容 + 模板 + 背景；``product_id`` 标归属。
- ``field_values``（**按套独立**）：``(set_id, field_def_id)`` → 该套对该字段的提取内容/序号/排序/启用。

对外仍以 ``PromptSet`` + ``ReferenceField`` 暴露：``load_prompt_set`` 把「定义 ⨝ 值」join 成
``ReferenceField``（``id``=field_def_id，``reference_name``/``field_type`` 取定义，``prompt``/
``sequence_number``/``sort_order``/``enabled`` 取值），下游 ``resolve_prompt_template`` / UI 无需感知拆表。
token ``{{field:uuid}}`` 里的 uuid = **定义 id**，故跨套/迁移后引用稳定。

写路径约定（保证 token 不悬空）：
- 单字段新增 ``allocate_field_in_set`` 走 ``_get_or_create_definition``（按名+类型全局取或建），返回 canonical id；
- 批量保存 ``replace_prompt_set_fields`` 只按 ``field.id`` upsert 定义（保 id、可改名/类型），不按名去重；
- 去重（合并同名为一个全局定义）只在**一次性迁移** ``_migrate_legacy_reference_fields`` 做。
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
    field_token,
    normalize_reference_name,
    now_iso,
    reference_fields_from_legacy,
)


def _default_db_path() -> Path:
    """prompts.db 与主配置同目录（取 DEFAULT_CONFIG_PATH 的父目录）。"""
    return Path(config_store.DEFAULT_CONFIG_PATH).parent / "prompts.db"


# 序号原子分配的进程内锁。
_ALLOC_LOCK = threading.RLock()


@dataclass(frozen=True)
class PromptSet:
    """一套提示词（某产品的一份）。reference_fields = 定义 ⨝ 值的视图（含全部，过滤由上层做）。"""

    id: str
    name: str
    prompt_template: str
    background_prompt: str
    template_version: int
    field_seq_max: int
    reference_fields: tuple[ReferenceField, ...]
    product_id: str = ""


@dataclass(frozen=True)
class FieldDefinition:
    """全局唯一字段定义。id/uuid 仅内部用，不显示给用户。"""

    id: str
    reference_name: str
    field_type: str
    global_content: str
    legacy_key: str = ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS field_definitions (
    id TEXT PRIMARY KEY,
    reference_name TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT '文本',
    global_content TEXT NOT NULL DEFAULT '',
    legacy_key TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS prompt_sets (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    prompt_template TEXT NOT NULL DEFAULT '',
    background_prompt TEXT NOT NULL DEFAULT '',
    template_version INTEGER NOT NULL DEFAULT 1,
    field_seq_max INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS field_values (
    set_id TEXT NOT NULL REFERENCES prompt_sets(id) ON DELETE CASCADE,
    field_def_id TEXT NOT NULL REFERENCES field_definitions(id) ON DELETE CASCADE,
    sequence_number INTEGER NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT,
    deleted_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (set_id, field_def_id)
);
CREATE INDEX IF NOT EXISTS idx_field_values_set ON field_values(set_id);
CREATE INDEX IF NOT EXISTS idx_field_defs_name ON field_definitions(reference_name, field_type);
"""


def _connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """打开连接、建表（幂等）、补列、并把旧 ``reference_fields`` 一次性迁到新表。"""
    path = Path(db_path) if db_path is not None else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    _ensure_schema(conn)
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """旧库补 product_id 列；旧 reference_fields 表存在且新值表为空时一次性迁移。"""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(prompt_sets)")}
    if "product_id" not in cols:
        conn.execute("ALTER TABLE prompt_sets ADD COLUMN product_id TEXT NOT NULL DEFAULT ''")
    if _table_exists(conn, "reference_fields"):
        has_values = conn.execute("SELECT 1 FROM field_values LIMIT 1").fetchone() is not None
        if not has_values:
            _migrate_legacy_reference_fields(conn)
    conn.commit()


def _migrate_legacy_reference_fields(conn: sqlite3.Connection) -> None:
    """把旧 ``reference_fields``（每套各一份字段）迁成 全局 field_definitions + 按套 field_values。

    去重键 = (归一化 reference_name, field_type)，保最早出现的 field id 作 canonical 定义 id；
    全局默认内容取该定义第一次出现时的 prompt。每套的 prompt_template 里 ``{{field:旧id}}`` 同步
    改写成 canonical id。保 token 稳定，绝不丢字段内容。
    """
    set_rows = conn.execute(
        "SELECT id, prompt_template FROM prompt_sets ORDER BY created_at, id"
    ).fetchall()
    field_rows = conn.execute(
        "SELECT * FROM reference_fields ORDER BY set_id, sort_order, sequence_number"
    ).fetchall()

    canonical: dict[tuple[str, str], str] = {}   # (norm_name, type) -> def id
    id_map: dict[str, str] = {}                  # 旧 field id -> canonical def id
    ts = now_iso()
    for row in field_rows:
        ftype = (row["field_type"] or "文本")
        key = (normalize_reference_name(row["reference_name"]), ftype)
        canonical_id = canonical.get(key)
        if canonical_id is None:
            canonical_id = row["id"]
            canonical[key] = canonical_id
            conn.execute(
                "INSERT OR IGNORE INTO field_definitions "
                "(id, reference_name, field_type, global_content, legacy_key, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (canonical_id, row["reference_name"], ftype, row["prompt"] or "",
                 row["legacy_key"] or "", row["created_at"] or ts, row["updated_at"] or ts),
            )
        id_map[row["id"]] = canonical_id

    for row in field_rows:
        def_id = id_map[row["id"]]
        conn.execute(
            "INSERT OR IGNORE INTO field_values "
            "(set_id, field_def_id, sequence_number, prompt, sort_order, enabled, "
            " created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["set_id"], def_id, int(row["sequence_number"]), row["prompt"] or "",
             int(row["sort_order"]), 1 if row["enabled"] else 0,
             row["created_at"] or ts, row["updated_at"] or ts, row["deleted_at"] or ""),
        )

    for set_row in set_rows:
        template = set_row["prompt_template"] or ""
        if not template:
            continue
        new_template = template
        for old_id, def_id in id_map.items():
            if old_id != def_id:
                new_template = new_template.replace(field_token(old_id), field_token(def_id))
        if new_template != template:
            conn.execute(
                "UPDATE prompt_sets SET prompt_template = ? WHERE id = ?",
                (new_template, set_row["id"]),
            )


def init_db(db_path: Path | str | None = None) -> None:
    """显式建表（建表已在 _connect 幂等执行，单独暴露便于初始化/测试）。"""
    conn = _connect(db_path)
    try:
        conn.commit()
    finally:
        conn.close()


# ===== 定义 get-or-create / upsert =====


def _get_or_create_definition(
    conn: sqlite3.Connection,
    *,
    field_id: str | None,
    reference_name: str,
    field_type: str,
    prompt: str = "",
    legacy_key: str = "",
) -> str:
    """按 (归一化名, 类型) 全局取或建定义，返回 def id。

    已有同名同类型 → 复用其 id（全局唯一）。否则新建：``field_id`` 给定且未占用时用作新 id（保 token 稳定），
    否则随机 uuid。``prompt`` 作新定义的 global_content（仅新建时写）。
    """
    ftype = field_type or "文本"
    norm = normalize_reference_name(reference_name)
    for row in conn.execute("SELECT id, reference_name, field_type FROM field_definitions"):
        if normalize_reference_name(row["reference_name"]) == norm and (row["field_type"] or "文本") == ftype:
            return row["id"]
    new_id = field_id or str(uuid.uuid4())
    if conn.execute("SELECT 1 FROM field_definitions WHERE id = ?", (new_id,)).fetchone() is not None:
        new_id = str(uuid.uuid4())
    ts = now_iso()
    conn.execute(
        "INSERT INTO field_definitions "
        "(id, reference_name, field_type, global_content, legacy_key, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (new_id, str(reference_name).strip() or norm, ftype, prompt or "", legacy_key or "", ts, ts),
    )
    return new_id


def _upsert_definition_by_id(conn: sqlite3.Connection, field: ReferenceField) -> str:
    """批量保存路径：按 field.id upsert 定义。存在则改名/类型（名是全局的，全产品生效）；
    不存在则按名+类型全局取或建（新字段）。返回最终 def id。"""
    ftype = field.field_type or "文本"
    existing = conn.execute(
        "SELECT id FROM field_definitions WHERE id = ?", (field.id,)
    ).fetchone()
    if existing is not None:
        conn.execute(
            "UPDATE field_definitions SET reference_name = ?, field_type = ?, updated_at = ? WHERE id = ?",
            (field.reference_name, ftype, now_iso(), field.id),
        )
        return field.id
    return _get_or_create_definition(
        conn,
        field_id=field.id,
        reference_name=field.reference_name,
        field_type=ftype,
        prompt=field.prompt,
        legacy_key=field.legacy_key,
    )


def _insert_value(conn: sqlite3.Connection, set_id: str, def_id: str, field: ReferenceField) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO field_values "
        "(set_id, field_def_id, sequence_number, prompt, sort_order, enabled, "
        " created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (set_id, def_id, int(field.sequence_number), field.prompt or "", int(field.sort_order),
         1 if field.enabled else 0, field.created_at or now_iso(),
         field.updated_at or now_iso(), field.deleted_at or ""),
    )


def _write_fields(conn: sqlite3.Connection, set_id: str, fields: Iterable[ReferenceField]) -> int:
    """把 fields 拆成 定义+值 写入；返回新字段最大序号。"""
    seq_max = 0
    for field in fields:
        def_id = _upsert_definition_by_id(conn, field)
        _insert_value(conn, set_id, def_id, field)
        seq_max = max(seq_max, int(field.sequence_number))
    return seq_max


# ===== 读 =====


def _row_to_field(row: sqlite3.Row, set_id: str) -> ReferenceField:
    return ReferenceField(
        id=row["field_def_id"],
        scope_id=set_id,
        sequence_number=int(row["sequence_number"]),
        reference_name=row["reference_name"],
        prompt=row["prompt"] or "",
        sort_order=int(row["sort_order"]),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        deleted_at=row["deleted_at"] or "",
        field_type=row["field_type"] or "文本",
        legacy_key=row["legacy_key"] or "",
    )


def _load_set_row(conn: sqlite3.Connection, set_id: str) -> PromptSet | None:
    row = conn.execute("SELECT * FROM prompt_sets WHERE id = ?", (set_id,)).fetchone()
    if row is None:
        return None
    field_rows = conn.execute(
        "SELECT v.*, d.reference_name, d.field_type, d.legacy_key "
        "FROM field_values v JOIN field_definitions d ON d.id = v.field_def_id "
        "WHERE v.set_id = ? ORDER BY v.sort_order, v.sequence_number",
        (set_id,),
    ).fetchall()
    return PromptSet(
        id=row["id"],
        name=row["name"],
        prompt_template=row["prompt_template"] or "",
        background_prompt=row["background_prompt"] or "",
        template_version=int(row["template_version"]),
        field_seq_max=int(row["field_seq_max"]),
        reference_fields=tuple(_row_to_field(r, set_id) for r in field_rows),
        product_id=row["product_id"] or "",
    )


def load_prompt_set(set_id: str, db_path: Path | str | None = None) -> PromptSet | None:
    """按 set_id 载出整套（定义 ⨝ 值）。不存在返回 None。"""
    conn = _connect(db_path)
    try:
        return _load_set_row(conn, set_id)
    finally:
        conn.close()


def list_prompt_sets(db_path: Path | str | None = None) -> tuple[tuple[str, str], ...]:
    """返回全部套 (id, name)。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT id, name FROM prompt_sets ORDER BY created_at, name").fetchall()
        return tuple((row["id"], row["name"]) for row in rows)
    finally:
        conn.close()


def list_sets_for_product(product_id: str, db_path: Path | str | None = None) -> tuple[tuple[str, str], ...]:
    """返回某产品拥有的套 (id, name)，供「一产品可多套」选择器/管理用。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name FROM prompt_sets WHERE product_id = ? ORDER BY created_at, name",
            (product_id,),
        ).fetchall()
        return tuple((row["id"], row["name"]) for row in rows)
    finally:
        conn.close()


def list_field_definitions(db_path: Path | str | None = None) -> tuple[FieldDefinition, ...]:
    """全部全局字段定义（按创建序）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM field_definitions ORDER BY created_at, reference_name"
        ).fetchall()
        return tuple(
            FieldDefinition(
                id=row["id"],
                reference_name=row["reference_name"],
                field_type=row["field_type"] or "文本",
                global_content=row["global_content"] or "",
                legacy_key=row["legacy_key"] or "",
            )
            for row in rows
        )
    finally:
        conn.close()


def get_field_definition(def_id: str, db_path: Path | str | None = None) -> FieldDefinition | None:
    """按 id 取定义（供 @global 解析、跨套显示名）。不存在返回 None。"""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM field_definitions WHERE id = ?", (def_id,)).fetchone()
        if row is None:
            return None
        return FieldDefinition(
            id=row["id"],
            reference_name=row["reference_name"],
            field_type=row["field_type"] or "文本",
            global_content=row["global_content"] or "",
            legacy_key=row["legacy_key"] or "",
        )
    finally:
        conn.close()


def set_owner(set_id: str, db_path: Path | str | None = None) -> str:
    """取某套的 product_id（归属）；不存在返回空串。"""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT product_id FROM prompt_sets WHERE id = ?", (set_id,)).fetchone()
        return (row["product_id"] or "") if row is not None else ""
    finally:
        conn.close()


def assign_set_owner(set_id: str, product_id: str, db_path: Path | str | None = None) -> None:
    """把某套归到某产品名下（幂等）。"""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE prompt_sets SET product_id = ?, updated_at = ? WHERE id = ?",
            (product_id, now_iso(), set_id),
        )
        conn.commit()
    finally:
        conn.close()


# ===== 写：建套 / 改套 / 改名 / 删套 =====


def create_prompt_set(
    name: str,
    *,
    product_id: str = "",
    prompt_template: str = "",
    background_prompt: str = "",
    template_version: int = 1,
    set_id: str | None = None,
    fields: Iterable[ReferenceField] = (),
    db_path: Path | str | None = None,
) -> str:
    """新建一套，返回 set_id。fields 拆成 定义+值 写入；field_seq_max 取 fields 最大序号。"""
    new_id = set_id or str(uuid.uuid4())
    field_tuple = tuple(fields)
    timestamp = now_iso()
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO prompt_sets "
            "(id, product_id, name, prompt_template, background_prompt, template_version, "
            " field_seq_max, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, product_id or "", name, prompt_template or "", background_prompt or "",
             int(template_version), 0, timestamp, timestamp),
        )
        seq_max = _write_fields(conn, new_id, field_tuple)
        conn.execute(
            "UPDATE prompt_sets SET field_seq_max = ? WHERE id = ?", (seq_max, new_id)
        )
        conn.commit()
        return new_id
    finally:
        conn.close()


def create_product_set_with_all_fields(
    name: str,
    *,
    product_id: str,
    db_path: Path | str | None = None,
) -> str:
    """为新产品建一套：给**每个全局字段定义**各建一条空内容 value（结构齐全、内容全空）。"""
    conn = _connect(db_path)
    try:
        new_id = str(uuid.uuid4())
        timestamp = now_iso()
        conn.execute(
            "INSERT INTO prompt_sets "
            "(id, product_id, name, prompt_template, background_prompt, template_version, "
            " field_seq_max, created_at, updated_at) VALUES (?, ?, ?, '', '', 1, 0, ?, ?)",
            (new_id, product_id, name, timestamp, timestamp),
        )
        defs = conn.execute(
            "SELECT id FROM field_definitions ORDER BY created_at, reference_name"
        ).fetchall()
        seq = 0
        for row in defs:
            seq += 1
            conn.execute(
                "INSERT INTO field_values "
                "(set_id, field_def_id, sequence_number, prompt, sort_order, enabled, "
                " created_at, updated_at, deleted_at) VALUES (?, ?, ?, '', ?, 1, ?, ?, '')",
                (new_id, row["id"], seq, seq, timestamp, timestamp),
            )
        conn.execute("UPDATE prompt_sets SET field_seq_max = ? WHERE id = ?", (seq, new_id))
        conn.commit()
        return new_id
    finally:
        conn.close()


def clone_prompt_set(
    source_set_id: str,
    *,
    name: str | None = None,
    new_set_id: str | None = None,
    product_id: str = "",
    db_path: Path | str | None = None,
) -> str:
    """把一套复制成独立新套：复制全部 value 行（**定义全局共享，不改 def id**）、模板原样照搬
    （token 引用定义 id，无需改写）。源套不存在抛 KeyError。返回新 set_id。"""
    conn = _connect(db_path)
    try:
        src = conn.execute("SELECT * FROM prompt_sets WHERE id = ?", (source_set_id,)).fetchone()
        if src is None:
            raise KeyError(f"提示词套不存在：{source_set_id!r}")
        new_id = new_set_id or str(uuid.uuid4())
        timestamp = now_iso()
        conn.execute(
            "INSERT INTO prompt_sets "
            "(id, product_id, name, prompt_template, background_prompt, template_version, "
            " field_seq_max, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, product_id or "", name if name is not None else src["name"],
             src["prompt_template"] or "", src["background_prompt"] or "",
             int(src["template_version"]), int(src["field_seq_max"]), timestamp, timestamp),
        )
        for row in conn.execute("SELECT * FROM field_values WHERE set_id = ?", (source_set_id,)):
            conn.execute(
                "INSERT INTO field_values "
                "(set_id, field_def_id, sequence_number, prompt, sort_order, enabled, "
                " created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id, row["field_def_id"], int(row["sequence_number"]), row["prompt"] or "",
                 int(row["sort_order"]), 1 if row["enabled"] else 0,
                 row["created_at"] or timestamp, row["updated_at"] or timestamp, row["deleted_at"] or ""),
            )
        conn.commit()
        return new_id
    finally:
        conn.close()


def rename_prompt_set(set_id: str, name: str, db_path: Path | str | None = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE prompt_sets SET name = ?, updated_at = ? WHERE id = ?",
            (name, now_iso(), set_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_prompt_set(set_id: str, db_path: Path | str | None = None) -> None:
    """删一套（其 field_values 随外键级联删；定义是全局的，不动）。"""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM field_values WHERE set_id = ?", (set_id,))
        conn.execute("DELETE FROM prompt_sets WHERE id = ?", (set_id,))
        conn.commit()
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
    """原子整体替换一套的字段值（删旧 value、按 field.id upsert 定义并写新 value）+ 按需改模板/背景/版本。

    定义按 field.id upsert（改名/类型=全局生效），不按名去重——保证模板里 ``{{field:id}}`` 不悬空。
    field_seq_max 取「现存值」与「新字段最大序号」的较大者，绝不回退。
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
        conn.execute("DELETE FROM field_values WHERE set_id = ?", (set_id,))
        seq_written = _write_fields(conn, set_id, field_tuple)
        new_seq_max = max(int(row["field_seq_max"]), seq_written, 0)
        conn.execute(
            "UPDATE prompt_sets SET prompt_template = ?, background_prompt = ?, "
            "template_version = ?, field_seq_max = ?, updated_at = ? WHERE id = ?",
            (new_template or "", new_background or "", new_version, new_seq_max, now_iso(), set_id),
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
    """原子新增一个字段：按名+类型全局取或建定义，在本套分配下一序号并插 value。

    返回 (新建/复用的 ReferenceField, 新 field_seq_max)。并发不撞号（BEGIN IMMEDIATE + 进程内锁）。
    """
    with _ALLOC_LOCK:
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            srow = conn.execute(
                "SELECT field_seq_max FROM prompt_sets WHERE id = ?", (set_id,)
            ).fetchone()
            if srow is None:
                conn.rollback()
                raise KeyError(f"提示词套不存在：{set_id!r}")
            def_id = _get_or_create_definition(
                conn,
                field_id=None,
                reference_name=reference_name,
                field_type=field_type or "文本",
                prompt=prompt,
                legacy_key=legacy_key,
            )
            existing = conn.execute(
                "SELECT * FROM field_values WHERE set_id = ? AND field_def_id = ?",
                (set_id, def_id),
            ).fetchone()
            timestamp = now_iso()
            new_seq_max = int(srow["field_seq_max"])
            if existing is None:
                new_seq_max += 1
                conn.execute(
                    "INSERT INTO field_values "
                    "(set_id, field_def_id, sequence_number, prompt, sort_order, enabled, "
                    " created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, '')",
                    (set_id, def_id, new_seq_max, prompt or "", new_seq_max, timestamp, timestamp),
                )
                conn.execute(
                    "UPDATE prompt_sets SET field_seq_max = ?, updated_at = ? WHERE id = ?",
                    (new_seq_max, timestamp, set_id),
                )
                seq_used, prompt_used, created_at = new_seq_max, prompt or "", timestamp
            else:
                seq_used = int(existing["sequence_number"])
                prompt_used = existing["prompt"] or ""
                created_at = existing["created_at"] or timestamp
            conn.commit()
            field = ReferenceField(
                id=def_id,
                scope_id=set_id,
                sequence_number=seq_used,
                reference_name=str(reference_name),
                prompt=prompt_used,
                sort_order=seq_used,
                enabled=True,
                created_at=created_at,
                updated_at=timestamp,
                deleted_at="",
                field_type=field_type or "文本",
                legacy_key=legacy_key or "",
            )
            return field, new_seq_max
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
    """重建 reference_fields（保 id）。scope_id 置 set_id；缺 id 的项跳过（与旧逻辑一致）。"""
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
    product_id: str = "",
    db_path: Path | str | None = None,
) -> str:
    """从一个产品的原始 JSON payload 重建提示词、建一套 set，返回 set_id（保 field id）。

    优先用 reference_fields（保 id）；为空则从 extraction_prompt 走旧版解析。
    prompt_template 缺失且有字段时用 default_prompt_template 合成。字段经 create_prompt_set 拆成 定义+值。
    """
    background_prompt = _optional_str(payload, "background_prompt", "")
    extraction_prompt = _optional_str(payload, "extraction_prompt", "")
    new_id = set_id or str(uuid.uuid4())

    reference_fields = _fields_from_payload(payload.get("reference_fields"), new_id)
    if not reference_fields:
        reference_fields = reference_fields_from_legacy(extraction_prompt, scope_id=new_id)

    prompt_template = _optional_str(payload, "prompt_template", "")
    if not prompt_template and reference_fields:
        prompt_template = default_prompt_template(reference_fields, background_prompt)

    template_version = _int_or(payload.get("template_version"), 1)
    set_name = name if name is not None else (_optional_str(payload, "name", "") or new_id)

    return create_prompt_set(
        set_name,
        product_id=product_id,
        prompt_template=prompt_template,
        background_prompt=background_prompt,
        template_version=template_version,
        set_id=new_id,
        fields=reference_fields,
        db_path=db_path,
    )
