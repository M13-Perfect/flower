# Frontend bug sweep plan

## Scope

Fix the current React/FastAPI editor issues reported during manual UI review:

1. Canvas selection changes trigger a full Fabric canvas rehydrate.
2. Large production canvases render at raw size and make the main drawing area look like multiple boards.
3. Fabric's upper canvas exposes native dragging, which can interfere with pointer interactions.
4. The UI has no direct add-text or add-asset controls.

## Evidence baseline

- `npm test --workspace @flower/desktop`: 25 passed before fixes.
- `npm test --workspace @flower/api`: 29 passed before fixes.
- Browser DOM after applying the birth flower template showed two Fabric canvases sized `3000x3000`, with the canvas container extending far outside the visible drawing panel.
- The current sidebar buttons were only order parsing, layer rows, export, and JSON actions; no add-text or add-asset command existed.

## Implementation tasks

1. Add pure tests and helpers for canvas preview scaling.
2. Add pure tests and helpers for adding text and imported asset layers.
3. Update `FabricCanvas` to use a scaled preview, avoid selection-triggered rehydration, and disable native canvas dragging.
4. Update `App` UI with explicit add text and add asset controls.
5. Re-run unit tests, lint/build checks, and browser smoke tests.
