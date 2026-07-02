from __future__ import annotations

from types import SimpleNamespace

from config_store import AppConfig, ProductConfig, active_product
from prompt_references import ReferenceField, field_token, system_token
from ui_app import BirthFlowerApp


class _Var:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _DumpBox:
    def __init__(self, dump):
        self._textbox = SimpleNamespace(dump=lambda *_args, **_kwargs: list(dump))


class _RawText:
    def __init__(self, owner: "_EditBox") -> None:
        self.owner = owner
        self.tags: list[tuple[str, str, str]] = []
        self.configured: set[str] = set()

    def tag_add(self, tag: str, start: str, end: str) -> None:
        self.tags.append((tag, start, end))

    def tag_config(self, tag: str, **_kwargs) -> None:
        self.configured.add(tag)

    def edit_reset(self) -> None:
        pass

    def dump(self, *_args, **_kwargs):
        return self.owner.dump


class _EditBox:
    def __init__(self, text: str = "", dump=None) -> None:
        self.text = text
        self.dump = dump or []
        self._textbox = _RawText(self)

    def delete(self, *_args) -> None:
        self.text = ""

    def insert(self, _index: str, value: str) -> None:
        self.text += value

    def get(self, *_args) -> str:
        return self.text

    def index(self, index: str) -> str:
        if index == "insert":
            return f"1.{len(self.text)}"
        return index


class _LineBox:
    """单行文本 + 哪些列带 'chip' tag 的最小 fake，喂给 _slash_query_before_cursor/_char_in_chip。"""

    def __init__(self, line: str, chip_cols: set[int]) -> None:
        self.line = line
        self._textbox = SimpleNamespace(
            tag_names=lambda idx: ("chip",) if int(idx.split(".")[1]) in chip_cols else ()
        )

    def get(self, *_args) -> str:
        return self.line

    def index(self, expr: str) -> str:
        if "chars" in expr:
            return f"1.{int(expr.split('+')[1].split('chars')[0])}"
        return f"1.{len(self.line)}"


def _field(
    *,
    field_id: str = "11111111-1111-4111-8111-111111111111",
    sequence_number: int = 3,
    name: str = "info3",
) -> ReferenceField:
    return ReferenceField(
        id=field_id,
        scope_id="birth-flower-card",
        sequence_number=sequence_number,
        reference_name=name,
        prompt="Extract value",
        sort_order=sequence_number,
        enabled=True,
        created_at="2026-06-23T00:00:00+00:00",
        updated_at="2026-06-23T00:00:00+00:00",
    )


def _app_with(field: ReferenceField, box=None):
    app = SimpleNamespace(
        config=AppConfig(
            products=(
                ProductConfig(
                    id="birth-flower-card",
                    name="Birth Flower",
                    reference_fields=(field,),
                    field_seq_max=field.sequence_number,
                    prompt_template=field_token(field.id),
                ),
            )
        ),
        background_prompt_text=box,
        field_defs=[],
    )
    app._tag_prompt_reference = lambda kind, ref_id, start, end: BirthFlowerApp._tag_prompt_reference(
        app, kind, ref_id, start, end
    )
    return app


def test_template_text_from_editor_round_trips_tagged_visible_references():
    field = _field(name="Birthday Month")
    dump = [
        ("text", "A ", "1.0"),
        ("tagon", "ref::" + field.id, "1.2"),
        ("tagon", "chip", "1.2"),
        ("text", "/Birthday Month", "1.2"),
        ("tagoff", "chip", "1.17"),
        ("tagoff", "ref::" + field.id, "1.17"),
        ("text", " B ", "1.17"),
        ("tagon", "src::order_information", "1.20"),
        ("text", "/Order Info", "1.20"),
        ("tagoff", "src::order_information", "1.31"),
    ]
    app = _app_with(field, _DumpBox(dump))

    assert BirthFlowerApp._template_text_from_editor(app) == (
        f"A {field_token(field.id)} B {system_token('order_information')}"
    )


def test_render_template_into_editor_shows_names_not_tokens():
    field = _field(name="Birthday Month")
    box = _EditBox()
    app = _app_with(field, box)

    BirthFlowerApp._render_template_into_editor(app, f"Before {field_token(field.id)}")

    assert box.text == "Before /Birthday Month"
    assert field.id not in box.text
    assert ("ref::" + field.id, "1.7", "1.22") in box._textbox.tags


def test_slash_candidates_keep_label_display_and_token_separate():
    field = _field(name="Birthday Month")
    app = _app_with(field)

    candidate = BirthFlowerApp._prompt_reference_candidates(app, "Birthday")[0]

    assert candidate["label"] == "/#3 Birthday Month"
    assert candidate["display_name"] == "/Birthday Month"
    assert candidate["ref_kind"] == "field"
    assert candidate["ref_id"] == field.id


def test_insert_slash_candidate_inserts_visible_name_and_tags_token_identity():
    field = _field(name="Birthday Month")
    box = _EditBox("/")
    app = _app_with(field, box)
    app._slash_candidates = [
        {
            "label": "/#3 Birthday Month",
            "display_name": "/Birthday Month",
            "ref_kind": "field",
            "ref_id": field.id,
        }
    ]
    app._slash_start_index = "1.0"
    app._slash_selected_index = 0
    app._hide_slash_popup = lambda: None
    app._persist_prompts = lambda: None

    BirthFlowerApp._insert_slash_candidate(app, 0)

    assert box.text == "/Birthday Month"
    assert field.id not in box.text
    assert ("ref::" + field.id, "1.0", "1.15") in box._textbox.tags


def test_slash_popup_triggers_after_chip_but_not_after_plain_text():
    field = _field()
    # "/字体" chip 占 0-2 列，用户在其后打 "/"（第 3 列）：应触发，否则游离 / 重渲成 //名称
    app = _app_with(field, _LineBox("/字体/", chip_cols={0, 1, 2}))
    app._char_in_chip = lambda col: BirthFlowerApp._char_in_chip(app, col)
    assert BirthFlowerApp._slash_query_before_cursor(app) is not None

    # "内容/" 普通文字后的 "/"（第 2 列）：不触发，护住 2cm/3cm、and/or
    app2 = _app_with(field, _LineBox("内容/", chip_cols=set()))
    app2._char_in_chip = lambda col: BirthFlowerApp._char_in_chip(app2, col)
    assert BirthFlowerApp._slash_query_before_cursor(app2) is None


def test_reference_fields_from_field_defs_persists_unsubmitted_name_var():
    field = _field(name="info3")
    app = _app_with(field)
    app.field_defs = [
        {
            "id": field.id,
            "key": field.id,
            "name_var": _Var("Birthday Month"),
            "inst_var": _Var("Extract value"),
            "type_var": _Var("text"),
        }
    ]

    updated = BirthFlowerApp._reference_fields_from_field_defs(app)

    assert updated[0].sequence_number == 3
    assert updated[0].reference_name == "Birthday Month"
    assert active_product(app.config).reference_fields[0].reference_name == "info3"
