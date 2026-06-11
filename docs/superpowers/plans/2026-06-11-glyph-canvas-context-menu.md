# Glyph Canvas Context Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse duplicate glyph UI actions, make inline text selection drive glyph apply/restore, hide editing selection boxes, and add canvas right-click operations.

**Architecture:** Keep glyph logic in `ui_app.py` and `glyph_panel.py`; do not add a new UI framework. Reuse one menu-building helper for Edit-menu glyph entries and canvas context menu entries so actions cannot drift.

**Tech Stack:** Python, Tkinter, pytest.

---

### Task 1: Regression Tests

**Files:**
- Modify: `tests/test_ui_app.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert the Edit menu has one `字形...` entry, the canvas binds `<Button-3>` / `<Button-2>`, inline selection can restore and apply glyphs, and inline editing suppresses selection controls.

- [ ] **Step 2: Verify red**

Run: `.\.venv\bin\python.exe -m pytest tests/test_ui_app.py -q`
Expected: failures for missing context-menu bindings, duplicate glyph menu labels, missing inline-selection sync, and selection controls still drawing during inline edit.

### Task 2: UI Implementation

**Files:**
- Modify: `ui_app.py`

- [ ] **Step 1: Collapse glyph menu entries**

Replace the five glyph-related Edit menu commands with a single `字形...` command that opens the glyph panel.

- [ ] **Step 2: Add canvas context menu**

Bind `<Button-3>` and `<Button-2>` on `preview_canvas`. On right-click, hit-test the clicked layer, select it, and show commands for edit text/material, delete, lock/unlock, layer ordering, `字形...`, `应用推荐字形`, and `恢复普通字符`.

- [ ] **Step 3: Sync inline text selection**

Add a helper that reads `inline_text_entry` selection using `sel.first`, converts it to a zero-based character index, and sets `selected_glyph_position`.

- [ ] **Step 4: Implement direct recommended apply**

Use `build_glyph_catalog()` and `recommended_glyph_variants()` for the selected character. Apply the first recommended variant with `apply_glyph_variant_to_current_text()`. If no recommended glyph exists, open the glyph panel.

- [ ] **Step 5: Hide edit boxes**

Skip `_draw_selection_controls()` while inline editing is active. Configure the inline `tk.Text` editor with `relief="flat"`, `borderwidth=0`, and `highlightthickness=0`.

### Task 3: Documentation And Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Document that `编辑 -> 字形...` is the single glyph panel entry, and that canvas right-click exposes layer operations plus glyph apply/restore.

- [ ] **Step 2: Verify green**

Run: `.\.venv\bin\python.exe -m pytest tests/test_ui_app.py tests/test_glyph_application.py tests/test_glyph_service.py -q`
Expected: all selected tests pass.

- [ ] **Step 3: Verify full suite**

Run: `.\.venv\bin\python.exe -m pytest -q`
Expected: all tests pass or any environment-only skip/failure is reported exactly.
