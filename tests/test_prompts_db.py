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
    assert {"prompt_sets", "field_definitions", "field_values"} <= names


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


def test_clone_prompt_set_shares_definitions_but_independent_values(db_path):
    src = prompts_db.create_prompt_set(
        "源套",
        prompt_template="头 " + field_token("id-a") + " 尾 " + field_token("id-b"),
        background_prompt="背景",
        fields=(_field("id-a", 1, "字段A", prompt="A源内容"), _field("id-b", 2, "字段B")),
        db_path=db_path,
    )
    clone_id = prompts_db.clone_prompt_set(src, name="副本", db_path=db_path)
    clone = prompts_db.load_prompt_set(clone_id, db_path=db_path)
    assert clone is not None and clone_id != src
    assert clone.name == "副本"
    # 定义全局共享：field id（=定义 id）不变，模板原样照搬（token 指向定义 id，无需改写）。
    assert [f.id for f in clone.reference_fields] == ["id-a", "id-b"]
    assert clone.prompt_template == "头 " + field_token("id-a") + " 尾 " + field_token("id-b")
    assert clone.background_prompt == "背景"
    assert clone.reference_fields[0].prompt == "A源内容"  # 值被复制过来
    # 值按套独立：清空副本的值，不影响源套的值。
    prompts_db.replace_prompt_set_fields(clone_id, (), db_path=db_path)
    assert len(prompts_db.load_prompt_set(clone_id, db_path=db_path).reference_fields) == 0
    assert len(prompts_db.load_prompt_set(src, db_path=db_path).reference_fields) == 2
    # 定义只有一份（全局唯一），不因克隆翻倍。
    assert len(prompts_db.list_field_definitions(db_path=db_path)) == 2


def test_clone_missing_source_raises(db_path):
    with pytest.raises(KeyError):
        prompts_db.clone_prompt_set("nope", db_path=db_path)


def test_new_product_set_gets_empty_values_for_all_global_fields(db_path):
    prompts_db.create_prompt_set(
        "A套", product_id="a",
        fields=(_field("id-a", 1, "花名", prompt="提取花名"), _field("id-b", 2, "人名", prompt="提取人名")),
        db_path=db_path,
    )
    new_set = prompts_db.create_product_set_with_all_fields("B套", product_id="b", db_path=db_path)
    loaded = prompts_db.load_prompt_set(new_set, db_path=db_path)
    # 结构齐全（两个全局字段都在），但内容全空。
    assert {f.reference_name for f in loaded.reference_fields} == {"花名", "人名"}
    assert all(f.prompt == "" for f in loaded.reference_fields)
    assert loaded.product_id == "b"
    # 没有新建定义（仍是 2 个全局定义）。
    assert len(prompts_db.list_field_definitions(db_path=db_path)) == 2


def test_legacy_reference_fields_migrate_to_definitions_and_values(db_path):
    # 手工造旧 schema：prompt_sets（无 product_id）+ reference_fields（每套各一份字段）。
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE prompt_sets (id TEXT PRIMARY KEY, name TEXT, prompt_template TEXT,
            background_prompt TEXT, template_version INTEGER, field_seq_max INTEGER,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE reference_fields (id TEXT PRIMARY KEY, set_id TEXT, sequence_number INTEGER,
            reference_name TEXT, prompt TEXT, sort_order INTEGER, enabled INTEGER,
            field_type TEXT, legacy_key TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT);
        """
    )
    conn.execute("INSERT INTO prompt_sets VALUES ('s1','套1',?, '',1,1,'','')", (field_token("fa"),))
    conn.execute("INSERT INTO prompt_sets VALUES ('s2','套2',?, '',1,1,'','')", (field_token("fb"),))
    # 两套各有一个「花名」字段（不同 uuid）→ 迁移后合并成一个全局定义。
    conn.execute("INSERT INTO reference_fields VALUES ('fa','s1',1,'花名','s1内容',1,1,'文本','k','','','')")
    conn.execute("INSERT INTO reference_fields VALUES ('fb','s2',1,'花名','s2内容',1,1,'文本','k','','','')")
    conn.commit()
    conn.close()

    s1 = prompts_db.load_prompt_set("s1", db_path=db_path)  # 触发一次性迁移
    s2 = prompts_db.load_prompt_set("s2", db_path=db_path)
    defs = prompts_db.list_field_definitions(db_path=db_path)
    assert len(defs) == 1 and defs[0].reference_name == "花名"  # 全局唯一
    canonical = defs[0].id
    # 内容按套独立，但都指向同一个全局定义；模板 token 改写成 canonical id。
    assert [f.id for f in s1.reference_fields] == [canonical]
    assert [f.id for f in s2.reference_fields] == [canonical]
    assert s1.reference_fields[0].prompt == "s1内容"
    assert s2.reference_fields[0].prompt == "s2内容"
    assert s1.prompt_template == field_token(canonical)
    assert s2.prompt_template == field_token(canonical)


def test_global_uniqueness_same_name_reuses_definition(db_path):
    set_id = prompts_db.create_prompt_set("套", product_id="a", db_path=db_path)
    f1, _ = prompts_db.allocate_field_in_set(set_id, "花名", field_type="文本", db_path=db_path)
    other = prompts_db.create_prompt_set("套2", product_id="b", db_path=db_path)
    f2, _ = prompts_db.allocate_field_in_set(other, "花名", field_type="文本", db_path=db_path)
    assert f1.id == f2.id  # 同名同类型 → 同一个全局定义
    assert len(prompts_db.list_field_definitions(db_path=db_path)) == 1


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
        # field_value 指向不存在的 set/定义 → 外键拒绝。
        conn.execute(
            "INSERT INTO field_definitions (id, reference_name, field_type) VALUES ('d1', '孤儿', '文本')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO field_values (set_id, field_def_id, sequence_number, sort_order) "
                "VALUES ('no-such-set', 'd1', 1, 1)"
            )
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
