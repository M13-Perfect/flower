import concurrent.futures
import json
import sqlite3

import pytest

import prompts_db
from prompt_references import ReferenceField, field_token, now_iso


def _field(field_id: str, seq: int, name: str, *, prompt: str = "", sort: int | None = None) -> ReferenceField:
    timestamp = now_iso()
    return ReferenceField(
        id=field_id,
        scope_id="ignored-on-insert",
        sequence_number=seq,
        reference_name=name,
        prompt=prompt,
        sort_order=seq if sort is None else sort,
        enabled=True,
        created_at=timestamp,
        updated_at=timestamp,
        field_type="文本",
        legacy_key=f"field{seq}",
    )


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "prompts.db"


def test_init_db_creates_tables(db_path):
    prompts_db.init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"prompt_sets", "reference_fields"} <= names


def test_create_and_load_round_trip(db_path):
    fields = (_field("id-a", 1, "字段A", prompt="A说明"), _field("id-b", 2, "字段B", prompt="B说明"))
    set_id = prompts_db.create_prompt_set(
        "我的套",
        prompt_template="模板 " + field_token("id-a"),
        background_prompt="背景",
        template_version=3,
        fields=fields,
        db_path=db_path,
    )
    loaded = prompts_db.load_prompt_set(set_id, db_path=db_path)
    assert loaded is not None
    assert loaded.name == "我的套"
    assert loaded.prompt_template == "模板 " + field_token("id-a")
    assert loaded.background_prompt == "背景"
    assert loaded.template_version == 3
    assert loaded.field_seq_max == 2
    assert [f.id for f in loaded.reference_fields] == ["id-a", "id-b"]
    # set_id 落到 scope_id 上
    assert all(f.scope_id == set_id for f in loaded.reference_fields)
    assert loaded.reference_fields[0].prompt == "A说明"


def test_load_missing_returns_none(db_path):
    assert prompts_db.load_prompt_set("does-not-exist", db_path=db_path) is None


def test_list_prompt_sets(db_path):
    a = prompts_db.create_prompt_set("套甲", db_path=db_path)
    b = prompts_db.create_prompt_set("套乙", db_path=db_path)
    listed = dict(prompts_db.list_prompt_sets(db_path=db_path))
    assert listed[a] == "套甲"
    assert listed[b] == "套乙"


def test_foreign_keys_enforced(db_path):
    prompts_db.init_db(db_path)
    conn = prompts_db._connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            prompts_db._insert_fields(conn, "no-such-set", (_field("orphan", 1, "孤儿"),))
            conn.commit()
    finally:
        conn.close()


def test_replace_prompt_set_fields_atomic(db_path):
    set_id = prompts_db.create_prompt_set(
        "套",
        fields=(_field("id-1", 1, "旧字段"),),
        prompt_template="old",
        db_path=db_path,
    )
    new_fields = (_field("id-2", 2, "新字段A"), _field("id-3", 3, "新字段B"))
    prompts_db.replace_prompt_set_fields(
        set_id,
        new_fields,
        prompt_template="new template",
        background_prompt="新背景",
        template_version=5,
        db_path=db_path,
    )
    loaded = prompts_db.load_prompt_set(set_id, db_path=db_path)
    assert [f.id for f in loaded.reference_fields] == ["id-2", "id-3"]
    assert loaded.prompt_template == "new template"
    assert loaded.background_prompt == "新背景"
    assert loaded.template_version == 5
    # field_seq_max 不回退
    assert loaded.field_seq_max == 3


def test_replace_keeps_existing_template_when_none(db_path):
    set_id = prompts_db.create_prompt_set(
        "套", prompt_template="keep me", background_prompt="keep bg", template_version=2, db_path=db_path
    )
    prompts_db.replace_prompt_set_fields(set_id, (_field("x", 1, "a"),), db_path=db_path)
    loaded = prompts_db.load_prompt_set(set_id, db_path=db_path)
    assert loaded.prompt_template == "keep me"
    assert loaded.background_prompt == "keep bg"
    assert loaded.template_version == 2


def test_replace_missing_set_raises(db_path):
    with pytest.raises(KeyError):
        prompts_db.replace_prompt_set_fields("nope", (), db_path=db_path)


def test_allocate_field_in_set_increments(db_path):
    set_id = prompts_db.create_prompt_set("套", db_path=db_path)
    field1, seq1 = prompts_db.allocate_field_in_set(set_id, "字段一", db_path=db_path)
    field2, seq2 = prompts_db.allocate_field_in_set(set_id, "字段二", db_path=db_path)
    assert (seq1, seq2) == (1, 2)
    assert field1.sequence_number == 1
    assert field2.sequence_number == 2
    loaded = prompts_db.load_prompt_set(set_id, db_path=db_path)
    assert loaded.field_seq_max == 2
    assert {f.id for f in loaded.reference_fields} == {field1.id, field2.id}


def test_allocate_field_missing_set_raises(db_path):
    with pytest.raises(KeyError):
        prompts_db.allocate_field_in_set("nope", "x", db_path=db_path)


def test_concurrent_allocate_do_not_duplicate_sequence(db_path):
    set_id = prompts_db.create_prompt_set("套", db_path=db_path)

    def alloc(name: str) -> int:
        field, _seq = prompts_db.allocate_field_in_set(set_id, name, db_path=db_path)
        return field.sequence_number

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        sequences = list(pool.map(alloc, ["A", "B", "C", "D"]))

    assert sorted(sequences) == [1, 2, 3, 4]


def test_migrate_preserves_field_ids(db_path):
    payload = {
        "name": "迁移产品",
        "background_prompt": "背景上下文",
        "reference_fields": [
            {
                "id": "uuid-keep-1",
                "sequence_number": 1,
                "reference_name": "月份",
                "prompt": "提取月份",
                "sort_order": 1,
                "enabled": True,
                "field_type": "素材",
                "legacy_key": "field1",
            },
            {
                "id": "uuid-keep-2",
                "sequence_number": 2,
                "reference_name": "字体",
                "prompt": "提取字体",
                "sort_order": 2,
                "enabled": True,
            },
        ],
        "field_seq_max": 2,
        "prompt_template": "模板 " + field_token("uuid-keep-1"),
        "template_version": 4,
    }
    set_id = prompts_db.migrate_product_payload(payload, db_path=db_path)
    loaded = prompts_db.load_prompt_set(set_id, db_path=db_path)
    assert [f.id for f in loaded.reference_fields] == ["uuid-keep-1", "uuid-keep-2"]
    assert loaded.name == "迁移产品"
    assert loaded.background_prompt == "背景上下文"
    assert loaded.template_version == 4
    assert loaded.field_seq_max == 2
    assert loaded.prompt_template == "模板 " + field_token("uuid-keep-1")


def test_migrate_with_explicit_set_id(db_path):
    payload = {"name": "p", "reference_fields": [{"id": "f1", "sequence_number": 1, "reference_name": "x"}]}
    set_id = prompts_db.migrate_product_payload(payload, set_id="my-set-id", db_path=db_path)
    assert set_id == "my-set-id"
    loaded = prompts_db.load_prompt_set("my-set-id", db_path=db_path)
    assert loaded.reference_fields[0].id == "f1"


def test_migrate_from_legacy_extraction_prompt(db_path):
    payload = {
        "name": "旧产品",
        "extraction_prompt": json.dumps(
            [
                {"key": "field1", "name": "生日月份", "type": "素材", "instruction": "提取月份"},
                {"key": "field2", "name": "字体编号", "type": "字体", "instruction": "提取字体"},
            ],
            ensure_ascii=False,
        ),
    }
    set_id = prompts_db.migrate_product_payload(payload, db_path=db_path)
    loaded = prompts_db.load_prompt_set(set_id, db_path=db_path)
    names = [f.reference_name for f in loaded.reference_fields]
    assert names == ["生日月份", "字体编号"]
    # 旧版无 prompt_template，应自动用 default_prompt_template 合成（含各 field token）
    for field in loaded.reference_fields:
        assert field_token(field.id) in loaded.prompt_template


def test_default_db_path_under_config_parent():
    expected = prompts_db.config_store.DEFAULT_CONFIG_PATH.parent / "prompts.db"
    assert prompts_db._default_db_path() == expected
