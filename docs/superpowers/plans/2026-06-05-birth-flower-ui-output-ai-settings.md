# Birth Flower UI Output AI Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved A2 UI with a classic menu, settings dialog, configurable AI recognition, and selectable PNG/SVG/DXF output.

**Architecture:** Keep Tkinter. Add non-sensitive configuration fields in `config_store.py`, pass explicit AI runtime settings through `parse_pipeline.py` into `gpt_parser.py`, and keep final generation behind the existing manual confirmation button. The settings dialog edits config and refreshes asset/font scans; the main window stays canvas-first.

**Tech Stack:** Python 3, Tkinter/ttk, pathlib, dataclasses, urllib OpenAI Responses API, pytest.

---

## File Structure

- Modify `models.py`: add `AIParseConfig` for runtime-only AI parameters.
- Modify `config_store.py`: add `AIProfile`, output format persistence, active AI profile persistence, and config normalization helpers.
- Modify `gpt_parser.py`: add explicit `project` and `organization` parameters; keep environment fallback.
- Modify `parse_pipeline.py`: accept `AIParseConfig`; skip GPT when AI is disabled.
- Modify `asset_resolver.py`: add general asset keys, filename matching, raster-embedding detection, and keep old month/flower compatibility.
- Modify `renderer.py`: expose preview cache support so realtime canvas redraw does not repeatedly parse unchanged SVG files.
- Modify `ui_app.py`: add menu bar, settings dialog, output checkboxes, status text, no permanent warnings text area.
- Modify `renderer.py`: no major rendering rewrite; only call existing `render_png`, `render_svg`, `render_dxf` independently from UI.
- Modify `README.md`: document settings UI and API configuration policy.
- Modify tests under `tests/`: add coverage for config, GPT headers, parse pipeline, and output selection helpers.

---

## Task 1: Config Model and Persistence

**Files:**
- Modify: `models.py`
- Modify: `config_store.py`
- Test: `tests/test_config_store.py`

- [ ] **Step 1: Write failing tests for output formats and AI profiles**

Append to `tests/test_config_store.py`:

```python
from config_store import AIProfile, DEFAULT_AI_PROFILE_NAME, active_ai_profile, normalize_output_formats


def test_save_and_load_config_keeps_output_formats_and_ai_profile(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(
        flower_dir=Path("assets"),
        font_source=Path("fonts"),
        output_path=tmp_path / "outputs" / "result.svg",
        output_formats=("png", "svg"),
        ai_profiles=(
            AIProfile(
                name="OpenAI shop",
                provider="openai",
                model="gpt-5-nano",
                api_key_env_var="SHOP_OPENAI_KEY",
                project_env_var="SHOP_OPENAI_PROJECT",
                org_env_var="SHOP_OPENAI_ORG",
                enabled=True,
            ),
        ),
        active_ai_profile="OpenAI shop",
    )

    save_config(config, path)
    raw = path.read_text(encoding="utf-8")
    loaded = load_config(path)

    assert "sk-" not in raw
    assert loaded.output_formats == ("png", "svg")
    assert loaded.active_ai_profile == "OpenAI shop"
    assert loaded.ai_profiles[0].api_key_env_var == "SHOP_OPENAI_KEY"


def test_load_config_supplies_default_ai_profile(tmp_path):
    config = load_config(tmp_path / "missing.json")

    profile = active_ai_profile(config)

    assert profile.name == DEFAULT_AI_PROFILE_NAME
    assert profile.provider == "openai"
    assert profile.model == "gpt-5-nano"
    assert profile.api_key_env_var == "OPENAI_API_KEY"


def test_normalize_output_formats_rejects_unknown_and_keeps_order():
    assert normalize_output_formats(["svg", "bad", "png", "svg"]) == ("svg", "png")
    assert normalize_output_formats([]) == ("svg", "dxf")
```

- [ ] **Step 2: Run config tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config_store.py -v
```

Expected: FAIL because `AIProfile`, `active_ai_profile`, and `normalize_output_formats` do not exist.

- [ ] **Step 3: Add runtime AI config to `models.py`**

Add below `ParseResult` in `models.py`:

```python
@dataclass(frozen=True)
class AIParseConfig:
    enabled: bool = True
    api_key: str | None = None
    model: str | None = None
    project: str | None = None
    organization: str | None = None
    timeout: float = 20.0
```

- [ ] **Step 4: Extend `config_store.py` dataclasses and helpers**

Replace the current `AppConfig` definition with:

```python
DEFAULT_OUTPUT_FORMATS = ("svg", "dxf")
SUPPORTED_OUTPUT_FORMATS = {"png", "svg", "dxf"}
DEFAULT_AI_PROFILE_NAME = "OpenAI default"


@dataclass(frozen=True)
class AIProfile:
    name: str = DEFAULT_AI_PROFILE_NAME
    provider: str = "openai"
    model: str = "gpt-5-nano"
    api_key_env_var: str = "OPENAI_API_KEY"
    project_env_var: str = "OPENAI_PROJECT"
    org_env_var: str = "OPENAI_ORG_ID"
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    flower_dir: Path = Path("BirthMonth flowers")
    font_source: Path = Path("Birthmonth_font.ttf")
    output_path: Path = DEFAULT_OUTPUT_PATH
    output_formats: tuple[str, ...] = DEFAULT_OUTPUT_FORMATS
    ai_profiles: tuple[AIProfile, ...] = (AIProfile(),)
    active_ai_profile: str = DEFAULT_AI_PROFILE_NAME
```

Add helpers below `save_config`:

```python
def normalize_output_formats(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or DEFAULT_OUTPUT_FORMATS:
        item = str(value).strip().casefold()
        if item in SUPPORTED_OUTPUT_FORMATS and item not in normalized:
            normalized.append(item)
    return tuple(normalized) or DEFAULT_OUTPUT_FORMATS


def active_ai_profile(config: AppConfig) -> AIProfile:
    for profile in config.ai_profiles:
        if profile.name == config.active_ai_profile:
            return profile
    return config.ai_profiles[0] if config.ai_profiles else AIProfile()
```

- [ ] **Step 5: Update config JSON load/save**

In `load_config`, after parsing payload, build profiles:

```python
    raw_profiles = payload.get("ai_profiles", [])
    profiles = tuple(_ai_profile_from_payload(item) for item in raw_profiles if isinstance(item, dict))
    if not profiles:
        profiles = (AIProfile(),)
    active_profile = _string_value(payload, "active_ai_profile", profiles[0].name)
```

Return:

```python
    return AppConfig(
        flower_dir=Path(_string_value(payload, "flower_dir", str(AppConfig().flower_dir))),
        font_source=Path(_string_value(payload, "font_source", str(AppConfig().font_source))),
        output_path=normalize_output_path(_string_value(payload, "output_path", str(AppConfig().output_path))),
        output_formats=normalize_output_formats(payload.get("output_formats")),
        ai_profiles=profiles,
        active_ai_profile=active_profile,
    )
```

In `save_config`, replace `payload` with:

```python
    payload = {
        "flower_dir": str(config.flower_dir),
        "font_source": str(config.font_source),
        "output_path": str(config.output_path),
        "output_formats": list(normalize_output_formats(config.output_formats)),
        "ai_profiles": [_ai_profile_to_payload(profile) for profile in config.ai_profiles],
        "active_ai_profile": active_ai_profile(config).name,
    }
```

Add below `_string_value`:

```python
def _ai_profile_from_payload(payload: dict[str, Any]) -> AIProfile:
    return AIProfile(
        name=_string_value(payload, "name", DEFAULT_AI_PROFILE_NAME),
        provider=_string_value(payload, "provider", "openai"),
        model=_string_value(payload, "model", "gpt-5-nano"),
        api_key_env_var=_string_value(payload, "api_key_env_var", "OPENAI_API_KEY"),
        project_env_var=_string_value(payload, "project_env_var", "OPENAI_PROJECT"),
        org_env_var=_string_value(payload, "org_env_var", "OPENAI_ORG_ID"),
        enabled=bool(payload.get("enabled", True)),
    )


def _ai_profile_to_payload(profile: AIProfile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "provider": profile.provider,
        "model": profile.model,
        "api_key_env_var": profile.api_key_env_var,
        "project_env_var": profile.project_env_var,
        "org_env_var": profile.org_env_var,
        "enabled": profile.enabled,
    }
```

- [ ] **Step 6: Run config tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config_store.py -v
```

Expected: PASS.

---

## Task 2: GPT Parser Explicit Headers

**Files:**
- Modify: `gpt_parser.py`
- Test: `tests/test_gpt_parser.py`

- [ ] **Step 1: Write failing test for explicit Project and Org**

Append to `tests/test_gpt_parser.py`:

```python
def test_parse_order_remark_with_gpt_prefers_explicit_project_and_org(monkeypatch):
    calls = []
    monkeypatch.setenv("OPENAI_PROJECT", "proj_env")
    monkeypatch.setenv("OPENAI_ORG_ID", "org_env")

    def fake_http_post(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        return {"output_text": '{"text":"Mina","month":5,"font":1,"flower":1,"warnings":[],"confidence":0.9}'}

    parse_order_remark_with_gpt(
        "Mina May font 1 flower 1",
        api_key="sk-test",
        model="gpt-5-nano",
        project="proj_ui",
        organization="org_ui",
        http_post=fake_http_post,
    )

    assert calls[0][2]["OpenAI-Project"] == "proj_ui"
    assert calls[0][2]["OpenAI-Organization"] == "org_ui"
```

- [ ] **Step 2: Run GPT parser tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_gpt_parser.py -v
```

Expected: FAIL because `project` and `organization` are unsupported.

- [ ] **Step 3: Update parser signature and header builder**

Change `parse_order_remark_with_gpt` signature to:

```python
def parse_order_remark_with_gpt(
    remark: str,
    api_key: str | None = None,
    model: str | None = None,
    project: str | None = None,
    organization: str | None = None,
    http_post: HttpPost | None = None,
    timeout: float = 20,
) -> ParseResult:
```

Change header creation:

```python
    headers = _build_headers(key, project=project, organization=organization)
```

Change `_build_headers`:

```python
def _build_headers(api_key: str, project: str | None = None, organization: str | None = None) -> dict[str, str]:
    """生成 OpenAI 请求头；显式参数优先，环境变量作为兼容回退。"""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    project_value = project or os.environ.get("OPENAI_PROJECT")
    organization_value = organization or os.environ.get("OPENAI_ORG_ID")
    if project_value:
        headers["OpenAI-Project"] = project_value
    if organization_value:
        headers["OpenAI-Organization"] = organization_value
    return headers
```

- [ ] **Step 4: Run GPT parser tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_gpt_parser.py -v
```

Expected: PASS.

---

## Task 3: Parse Pipeline AI Config

**Files:**
- Modify: `parse_pipeline.py`
- Test: `tests/test_parse_pipeline.py`

- [ ] **Step 1: Write failing tests for AI disable and runtime config**

Append to `tests/test_parse_pipeline.py`:

```python
from models import AIParseConfig


def test_parse_order_remark_auto_skips_gpt_when_ai_disabled():
    def forbidden_gpt(_remark):
        raise AssertionError("GPT should not be called")

    result = parse_order_remark_auto(
        "Name: Local June font 1 flower 1",
        ai_config=AIParseConfig(enabled=False),
        gpt_parser=forbidden_gpt,
        local_parser=lambda remark: ParseResult(text="Local", month=6, font=1, flower=1, confidence=0.8),
    )

    assert result.text == "Local"
    assert result.warnings == []


def test_parse_order_remark_auto_passes_ai_config_to_default_gpt():
    calls = []

    def fake_gpt(remark, api_key=None, model=None, project=None, organization=None, timeout=20):
        calls.append((remark, api_key, model, project, organization, timeout))
        return ParseResult(text="AI", month=6, font=1, flower=1, confidence=0.9)

    result = parse_order_remark_auto(
        "AI remark",
        ai_config=AIParseConfig(
            enabled=True,
            api_key="sk-session",
            model="gpt-5-nano",
            project="proj_ui",
            organization="org_ui",
            timeout=9,
        ),
        gpt_parser=fake_gpt,
        local_parser=lambda remark: ParseResult(text="Local", month=1, font=1, flower=1, confidence=0.5),
    )

    assert result.text == "AI"
    assert calls[0] == ("AI remark", "sk-session", "gpt-5-nano", "proj_ui", "org_ui", 9)
```

- [ ] **Step 2: Run parse pipeline tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_parse_pipeline.py -v
```

Expected: FAIL because `ai_config` is unsupported.

- [ ] **Step 3: Update parse pipeline**

Change imports in `parse_pipeline.py`:

```python
from collections.abc import Callable
from typing import Protocol

from birth_flower_parser import parse_order_remark
from gpt_parser import parse_order_remark_with_gpt
from models import AIParseConfig, ParseResult
```

Replace `Parser` alias with:

```python
class Parser(Protocol):
    def __call__(
        self,
        remark: str,
        api_key: str | None = None,
        model: str | None = None,
        project: str | None = None,
        organization: str | None = None,
        timeout: float = 20,
    ) -> ParseResult:
        ...


LocalParser = Callable[[str], ParseResult]
```

Change function signature:

```python
def parse_order_remark_auto(
    remark: str,
    ai_config: AIParseConfig | None = None,
    gpt_parser: Parser | None = None,
    local_parser: LocalParser | None = None,
) -> ParseResult:
```

Replace GPT block:

```python
    config = ai_config or AIParseConfig()
    gpt_error = "AI 识别已禁用"
    if config.enabled:
        try:
            gpt_result = gpt(
                remark,
                api_key=config.api_key,
                model=config.model,
                project=config.project,
                organization=config.organization,
                timeout=config.timeout,
            )
            if _is_complete(gpt_result):
                return _success_without_warnings(gpt_result)
            gpt_error = _incomplete_reason(gpt_result)
        except Exception as exc:
            gpt_error = str(exc)
```

Keep the existing local fallback block unchanged.

- [ ] **Step 4: Run parse pipeline tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_parse_pipeline.py -v
```

Expected: PASS.

---

## Task 4A: General Asset Filename Recognition

**Files:**
- Modify: `models.py`
- Modify: `asset_resolver.py`
- Test: `tests/test_asset_resolver.py`

- [ ] **Step 1: Write failing tests for general asset keys and matching**

Append to `tests/test_asset_resolver.py`:

```python
from asset_resolver import match_asset_by_name


def test_scan_flower_assets_adds_general_asset_metadata(tmp_path):
    flower = tmp_path / "June Rose.svg"
    flower.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L1 1"/></svg>', encoding="utf-8")

    assets = scan_flower_assets(tmp_path)

    assert assets[0].asset_key == "june-rose"
    assert assets[0].display_name == "Rose"
    assert assets[0].category == "birth_flower"
    assert assets[0].is_vector_safe is True
    assert assets[0].embedded_raster_warnings == []


def test_scan_flower_assets_detects_embedded_raster(tmp_path):
    flower = tmp_path / "June Rose.svg"
    flower.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="rose.png"/></svg>',
        encoding="utf-8",
    )

    assets = scan_flower_assets(tmp_path)

    assert assets[0].is_vector_safe is False
    assert "rose.png" in assets[0].embedded_raster_warnings[0]


def test_match_asset_by_name_prefers_asset_key_then_display_name(tmp_path):
    (tmp_path / "June Rose.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    (tmp_path / "April Daisy.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    assets = scan_flower_assets(tmp_path)

    assert match_asset_by_name(assets, "rose").display_name == "Rose"
    assert match_asset_by_name(assets, "april daisy").display_name == "Daisy"
    assert match_asset_by_name(assets, "unknown") is None
```

- [ ] **Step 2: Run asset resolver tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_asset_resolver.py -v
```

Expected: FAIL because `FlowerAsset` lacks metadata and `match_asset_by_name` does not exist.

- [ ] **Step 3: Extend `FlowerAsset` in `models.py`**

Replace `FlowerAsset` with:

```python
@dataclass(frozen=True)
class FlowerAsset:
    name: str
    month: int
    flower: int
    path: Path
    asset_key: str = ""
    display_name: str = ""
    category: str = "birth_flower"
    is_vector_safe: bool = True
    embedded_raster_warnings: tuple[str, ...] = ()
```

- [ ] **Step 4: Add filename key and raster detection in `asset_resolver.py`**

Add imports:

```python
import xml.etree.ElementTree as ET
```

When creating `FlowerAsset`, replace the constructor with:

```python
            display_name = _display_name(path.stem)
            raster_warnings = _embedded_raster_warnings(path)
            assets.append(
                FlowerAsset(
                    name=display_name,
                    month=month,
                    flower=index,
                    path=path,
                    asset_key=_asset_key(path.stem),
                    display_name=display_name,
                    category="birth_flower",
                    is_vector_safe=not raster_warnings,
                    embedded_raster_warnings=tuple(raster_warnings),
                )
            )
```

Add helpers:

```python
def match_asset_by_name(assets: list[FlowerAsset], query: str) -> FlowerAsset | None:
    needle = _asset_key(query)
    if not needle:
        return None
    for asset in assets:
        if needle == asset.asset_key or needle in asset.asset_key:
            return asset
    for asset in assets:
        if needle == _asset_key(asset.display_name or asset.name):
            return asset
    for asset in assets:
        if needle in _asset_key(asset.display_name or asset.name):
            return asset
    return None


def _asset_key(name: str) -> str:
    parts = re.findall(r"[a-z0-9]+", name.casefold())
    return "-".join(parts)


def _embedded_raster_warnings(path: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return [f"无法读取素材：{path}"]
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    warnings: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].casefold() != "image":
            continue
        href = element.attrib.get("href") or element.attrib.get("{http://www.w3.org/1999/xlink}href") or ""
        if href.casefold().endswith((".png", ".jpg", ".jpeg", ".webp")):
            warnings.append(f"素材嵌入位图文件，不是纯矢量：{href}")
    return warnings
```

- [ ] **Step 5: Run asset resolver tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_asset_resolver.py -v
```

Expected: PASS.

---

## Task 4B: Realtime Preview Cache

**Files:**
- Modify: `renderer.py`
- Modify: `ui_app.py`
- Test: `tests/test_renderer.py`

- [ ] **Step 1: Write failing test for preview cache reuse**

Append to `tests/test_renderer.py`:

```python
from renderer import PreviewCache


def test_preview_cache_reuses_polylines_when_file_and_layout_are_unchanged(tmp_path):
    flower_path = tmp_path / "RoseJune.svg"
    flower_path.write_text(
        '<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>',
        encoding="utf-8",
    )
    layout = EngravingLayout(flower_x=20, flower_y=30, flower_width=100, flower_height=100)
    cache = PreviewCache()

    first = cache.polylines(flower_path, layout)
    second = cache.polylines(flower_path, layout)

    assert second is first
    assert first == [[(20.0, 30.0), (120.0, 130.0)]]
```

- [ ] **Step 2: Run renderer tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_renderer.py -v
```

Expected: FAIL because `PreviewCache` does not exist.

- [ ] **Step 3: Add `PreviewCache` to `renderer.py`**

Add below `DEFAULT_LAYOUT`:

```python
class PreviewCache:
    def __init__(self) -> None:
        self._cache: dict[tuple[Path, float, EngravingLayout], list[list[tuple[float, float]]]] = {}

    def polylines(self, asset_path: Path | str, layout: EngravingLayout) -> list[list[tuple[float, float]]]:
        path = Path(asset_path)
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        key = (path, modified, layout)
        if key not in self._cache:
            self._cache[key] = flower_preview_polylines(path, layout)
        return self._cache[key]

    def clear(self) -> None:
        self._cache.clear()
```

- [ ] **Step 4: Use preview cache in `ui_app.py`**

Update renderer import:

```python
from renderer import PreviewCache, flower_preview_polylines, render_dxf, render_png, render_svg
```

Add in `BirthFlowerApp.__init__`:

```python
        self.preview_cache = PreviewCache()
```

Replace in `_draw_flower_preview`:

```python
            polylines = flower_preview_polylines(asset_path, layout)
```

with:

```python
            polylines = self.preview_cache.polylines(asset_path, layout)
```

In `_scan_assets`, after assigning assets:

```python
        self.preview_cache.clear()
```

- [ ] **Step 5: Run renderer and UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_renderer.py tests\test_ui_app.py -v
```

Expected: PASS.

---

## Task 4: Output Format Dispatch Helpers

**Files:**
- Modify: `ui_app.py`
- Test: `tests/test_ui_app.py`

- [ ] **Step 1: Write failing tests for output path and no-selection validation**

Append to `tests/test_ui_app.py`:

```python
from ui_app import output_path_for_format, validate_output_formats


def test_output_path_for_format_reuses_output_stem():
    assert output_path_for_format(Path("outputs/result.svg"), "svg") == Path("outputs/result.svg")
    assert output_path_for_format(Path("outputs/result.svg"), "dxf") == Path("outputs/result.dxf")
    assert output_path_for_format(Path("outputs/result.svg"), "png") == Path("outputs/result.png")


def test_validate_output_formats_requires_at_least_one_format():
    with pytest.raises(ValueError, match="至少选择一种输出格式"):
        validate_output_formats([])

    assert validate_output_formats(["svg", "bad", "png", "svg"]) == ("svg", "png")
```

- [ ] **Step 2: Run UI helper tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_app.py -v
```

Expected: FAIL because helper functions do not exist.

- [ ] **Step 3: Add helper imports and functions in `ui_app.py`**

Update imports:

```python
from config_store import AppConfig, active_ai_profile, load_config, normalize_output_formats, normalize_output_path, save_config
from renderer import PreviewCache, flower_preview_polylines, render_dxf, render_png, render_svg
```

Add near `dxf_path_for_svg`:

```python
def output_path_for_format(base_path: Path | str, output_format: str) -> Path:
    clean_format = output_format.strip().casefold()
    if clean_format not in {"png", "svg", "dxf"}:
        raise ValueError(f"不支持的输出格式：{output_format}")
    return Path(base_path).with_suffix(f".{clean_format}")


def validate_output_formats(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    formats = normalize_output_formats(values)
    selected = tuple(item for item in formats if item in {"png", "svg", "dxf"})
    if not selected:
        raise ValueError("至少选择一种输出格式")
    return selected
```

- [ ] **Step 4: Run UI helper tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_app.py -v
```

Expected: PASS.

---

## Task 5: Menu Bar and Settings Dialog

**Files:**
- Modify: `ui_app.py`
- Test: `tests/test_ui_app.py`

- [ ] **Step 1: Add UI state variables in `BirthFlowerApp.__init__`**

Add after `self.output_var`:

```python
        self.status_var = tk.StringVar(value="等待解析")
        self.output_format_vars = {
            "png": tk.BooleanVar(value="png" in self.config.output_formats),
            "svg": tk.BooleanVar(value="svg" in self.config.output_formats),
            "dxf": tk.BooleanVar(value="dxf" in self.config.output_formats),
        }
        self.session_api_key_var = tk.StringVar()
```

- [ ] **Step 2: Add menu builder call**

In `__init__`, before `_build_layout()`:

```python
        self._build_menu()
```

Add method:

```python
    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="导入备注...", command=self.import_remark_file)
        file_menu.add_command(label="打开输出目录", command=self.open_output_dir)
        file_menu.add_separator()
        file_menu.add_command(label="设置...", accelerator="Ctrl+,", command=self.open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.destroy)
        menu_bar.add_cascade(label="文件", menu=file_menu)
        menu_bar.add_cascade(label="编辑", menu=tk.Menu(menu_bar, tearoff=False))
        menu_bar.add_cascade(label="查看", menu=tk.Menu(menu_bar, tearoff=False))
        menu_bar.add_cascade(label="帮助", menu=tk.Menu(menu_bar, tearoff=False))
        self.root.config(menu=menu_bar)
        self.root.bind("<Control-comma>", lambda _event: self.open_settings())
```

- [ ] **Step 3: Replace permanent warnings frame with status line**

Remove the `warning_frame` block in `_build_layout`. Add the status label into the bottom output area:

```python
        ttk.Label(confirm_row, textvariable=self.status_var).pack(side="left")
```

Change `_set_warnings`:

```python
    def _set_warnings(self, warnings: list[str]) -> None:
        self.status_var.set("；".join(warnings) if warnings else "可生成")
```

- [ ] **Step 4: Move asset/font path controls into settings dialog**

Remove `asset_frame` from `_build_layout`. Keep only compact read-only labels near the parse result or sidebar:

```python
        self.current_asset_label = ttk.Label(form, textvariable=self.flower_asset_var)
        self._add_row(form, 1, "素材名", self.current_asset_label)
        self.current_font_label = ttk.Label(form, textvariable=self.font_asset_var)
        self._add_row(form, 2, "字体类型", self.current_font_label)
```

Keep layout numeric controls unchanged in the preview sidebar.

- [ ] **Step 5: Add output format checkboxes**

In `output_row`, before output path entry:

```python
        for output_format, label in (("png", "PNG"), ("svg", "SVG"), ("dxf", "DXF")):
            ttk.Checkbutton(output_row, text=label, variable=self.output_format_vars[output_format]).pack(side="left", padx=(8, 0))
```

- [ ] **Step 6: Add settings dialog methods**

Add methods to `BirthFlowerApp`:

```python
    def open_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("设置")
        window.transient(self.root)
        window.grab_set()
        notebook = ttk.Notebook(window)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)
        self._build_asset_settings_tab(notebook)
        self._build_font_settings_tab(notebook)
        self._build_ai_settings_tab(notebook)
        button_row = ttk.Frame(window)
        button_row.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(button_row, text="保存", command=lambda: self._save_settings_window(window)).pack(side="right")
        ttk.Button(button_row, text="取消", command=window.destroy).pack(side="right", padx=(0, 8))

    def _build_asset_settings_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="素材库")
        self._add_path_row(frame, 0, "素材目录", self.flower_dir_var, self.choose_flower_dir)
        ttk.Button(frame, text="重新扫描", command=lambda: self._scan_assets(show_errors=True)).grid(row=1, column=1, sticky="e", pady=8)

    def _build_font_settings_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="字体库")
        self._add_path_row(frame, 0, "字体文件/目录", self.font_source_var, self.choose_font_source)
        ttk.Button(frame, text="重新扫描", command=lambda: self._scan_assets(show_errors=True)).grid(row=1, column=1, sticky="e", pady=8)

    def _build_ai_settings_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="AI 识别")
        profile = active_ai_profile(self.config)
        self.ai_enabled_var = tk.BooleanVar(value=profile.enabled)
        self.ai_model_var = tk.StringVar(value=profile.model)
        self.ai_api_key_env_var = tk.StringVar(value=profile.api_key_env_var)
        self.ai_project_env_var = tk.StringVar(value=profile.project_env_var)
        self.ai_org_env_var = tk.StringVar(value=profile.org_env_var)
        ttk.Checkbutton(frame, text="启用 AI 优先解析", variable=self.ai_enabled_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=4)
        self._add_row(frame, 1, "模型", ttk.Entry(frame, textvariable=self.ai_model_var))
        self._add_row(frame, 2, "API Key 环境变量", ttk.Entry(frame, textvariable=self.ai_api_key_env_var))
        self._add_row(frame, 3, "Project 环境变量", ttk.Entry(frame, textvariable=self.ai_project_env_var))
        self._add_row(frame, 4, "Org 环境变量", ttk.Entry(frame, textvariable=self.ai_org_env_var))
        self._add_row(frame, 5, "临时 API Key", ttk.Entry(frame, textvariable=self.session_api_key_var, show="*"))
        ttk.Button(frame, text="测试连接", command=self.test_ai_connection).grid(row=6, column=1, sticky="e", pady=8)
```

- [ ] **Step 7: Add settings save method**

Add:

```python
    def _save_settings_window(self, window: tk.Toplevel) -> None:
        from config_store import AIProfile

        profile = AIProfile(
            name=active_ai_profile(self.config).name,
            provider="openai",
            model=self.ai_model_var.get().strip() or "gpt-5-nano",
            api_key_env_var=self.ai_api_key_env_var.get().strip() or "OPENAI_API_KEY",
            project_env_var=self.ai_project_env_var.get().strip() or "OPENAI_PROJECT",
            org_env_var=self.ai_org_env_var.get().strip() or "OPENAI_ORG_ID",
            enabled=bool(self.ai_enabled_var.get()),
        )
        self.config = AppConfig(
            flower_dir=Path(self.flower_dir_var.get()),
            font_source=Path(self.font_source_var.get()),
            output_path=Path(self.output_var.get()),
            output_formats=self._selected_output_formats_or_default(),
            ai_profiles=(profile,),
            active_ai_profile=profile.name,
        )
        save_config(self.config)
        self._scan_assets(show_errors=True)
        self.status_var.set("设置已保存")
        window.destroy()
```

- [ ] **Step 8: Add AI runtime config builder**

Add:

```python
    def _current_ai_config(self):
        import os

        from models import AIParseConfig

        profile = active_ai_profile(self.config)
        api_key = self.session_api_key_var.get().strip() or os.environ.get(profile.api_key_env_var)
        project = os.environ.get(profile.project_env_var)
        organization = os.environ.get(profile.org_env_var)
        return AIParseConfig(
            enabled=profile.enabled,
            api_key=api_key,
            model=profile.model,
            project=project,
            organization=organization,
        )
```

- [ ] **Step 9: Pass AI config into parsing**

Change `parse_remark`:

```python
    def parse_remark(self) -> None:
        result = parse_order_remark_auto(self.remark_var.get(), ai_config=self._current_ai_config())
        self._apply_parse_result(result)
```

- [ ] **Step 10: Run UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_app.py -v
```

Expected: PASS or fail only where tests need text updates from old month/font/flower labels.

---

## Task 6: Generate Selected Formats

**Files:**
- Modify: `ui_app.py`
- Test: `tests/test_ui_app.py`

- [ ] **Step 1: Add selected output helpers**

Add methods to `BirthFlowerApp`:

```python
    def _selected_output_formats(self) -> tuple[str, ...]:
        return validate_output_formats(
            [name for name, var in self.output_format_vars.items() if var.get()]
        )

    def _selected_output_formats_or_default(self) -> tuple[str, ...]:
        try:
            return self._selected_output_formats()
        except ValueError:
            return ("svg", "dxf")
```

- [ ] **Step 2: Replace forced SVG+DXF generation**

In `confirm_and_generate`, replace:

```python
            output_path = render_svg(design, normalize_output_path(self.output_var.get()))
            dxf_path = render_dxf(design, dxf_path_for_svg(output_path))
```

with:

```python
            selected_formats = self._selected_output_formats()
            base_output_path = normalize_output_path(self.output_var.get())
            generated_paths: list[Path] = []
            for output_format in selected_formats:
                target_path = output_path_for_format(base_output_path, output_format)
                if output_format == "svg":
                    generated_paths.append(render_svg(design, target_path))
                elif output_format == "dxf":
                    generated_paths.append(render_dxf(design, target_path))
                elif output_format == "png":
                    generated_paths.append(render_png(design, target_path))
```

Change success message:

```python
        messagebox.showinfo("生成完成", "已生成：\n" + "\n".join(str(path) for path in generated_paths))
```

- [ ] **Step 3: Save output formats with config**

Update `_save_current_config`:

```python
        self.config = AppConfig(
            flower_dir=Path(self.flower_dir_var.get()),
            font_source=Path(self.font_source_var.get()),
            output_path=Path(self.output_var.get()),
            output_formats=self._selected_output_formats_or_default(),
            ai_profiles=self.config.ai_profiles,
            active_ai_profile=self.config.active_ai_profile,
        )
        save_config(self.config)
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_app.py tests\test_renderer.py -v
```

Expected: PASS.

---

## Task 7: README and Full Verification

**Files:**
- Modify: `README.md`
- Test: all tests

- [ ] **Step 1: Update README AI section**

Replace the GPT setup text with:

```markdown
## AI 识别设置

程序支持在 `文件 -> 设置... -> AI 识别` 中配置 OpenAI 解析。

- 默认仍读取 PowerShell 环境变量 `OPENAI_API_KEY`。
- UI 可以临时输入 API Key，但只在本次程序运行期间生效，不会写入 `birth_flower_config.json`。
- 配置文件只保存模型名、环境变量名、Project/Org 环境变量名等非敏感字段。
- 未配置 API Key 时，程序会跳过 GPT 并使用本地规则解析。
- GPT 失败时不会自动生成最终文件，会回退本地规则或提示用户人工确认。

PowerShell 示例：

```powershell
$env:OPENAI_API_KEY="你的 OpenAI API Key"
$env:OPENAI_MODEL="gpt-5-nano"
$env:OPENAI_PROJECT="proj_xxx"
$env:OPENAI_ORG_ID="org_xxx"
.\.venv\Scripts\python.exe birth_flower_mvp.py
```
```

- [ ] **Step 2: Update README output section**

Add:

```markdown
## 输出格式

主界面支持勾选 `PNG`、`SVG`、`DXF`。默认勾选 `SVG` 和 `DXF`。PNG 依赖 Pillow；如果当前环境不可用，程序会给出错误提示。所有最终文件仍必须点击 `人工确认并生成` 后才会输出。
```

- [ ] **Step 3: Run all tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Expected: all tests PASS.

- [ ] **Step 4: Manual smoke test**

Run:

```powershell
.\.venv\Scripts\python.exe birth_flower_mvp.py
```

Expected:

- Window opens.
- Menu bar shows `文件 / 编辑 / 查看 / 帮助`.
- `文件 -> 设置...` opens settings.
- Asset and font paths can be saved.
- AI settings can be edited without saving API Key to config.
- Parse button still fills the editable result.
- Output checkboxes generate selected file types only after manual confirmation.

---

## Self-Review

Spec coverage:

- A2 menu design: Task 5.
- Settings dialog: Task 5.
- AI API edit/use without API Key persistence: Tasks 1, 2, 3, 5.
- General asset filename recognition and old month/flower compatibility: Task 4A.
- Realtime canvas rendering cache and SVG preview stability: Task 4B.
- Selectable PNG/SVG/DXF output: Tasks 1, 4, 6.
- Warnings removal: Task 5.
- README sync: Task 7.
- Tests: every implementation task starts with tests.

Risk notes:

- Tkinter UI tests should stay helper-focused because full `Toplevel` automation is brittle in headless runs.
- API connection testing should be a manual UI action or a fake HTTP test; pytest must not call the real OpenAI API.
- Multi-profile add/delete can be implemented as a single-profile first pass if implementation time is constrained, but the config shape already supports multiple profiles.
