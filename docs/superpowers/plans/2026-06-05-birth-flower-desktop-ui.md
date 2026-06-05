# Birth Flower Desktop UI Implementation Plan

## Scope

Implement the approved desktop UI design for the Birth Flower MVP without changing the Tkinter framework.

## Requirements

- Keep manual confirmation before final file generation.
- Preserve cross-platform behavior for Windows, macOS, and Linux.
- Do not bundle or download commercial fonts.
- Keep missing assets as friendly warnings.
- Keep PNG/SVG/DXF output behavior intact.
- Add tests for changed UI helpers and startup behavior.

## Implementation Steps

1. Reorganize the main `ui_app.py` screen into a production-oriented layout.
2. Keep order parsing, manual confirmation fields, live preview, and output controls visible.
3. Add UI state needed by the desktop workbench, including guide visibility and production action references.
4. Keep settings tabs for assets, fonts, AI parsing, output defaults, and layout defaults.
5. Update tests to cover startup and UI helper behavior.
6. Run the Tk startup smoke test and full pytest suite.

## Verification

- `python -m pytest -q`
- Tk smoke test that imports `BirthFlowerApp`, creates the root window, updates once, and destroys it.
