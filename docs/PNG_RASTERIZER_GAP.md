# PNG Rasterizer Gap

Current batch delivery defaults to SVG/DXF only. PNG is skipped unless `--png` or
`include_png=True` is requested.

Reason:
- Production PNG should rasterize the corrected full SVG so flower and outlined
  text match the SVG/DXF geometry.
- `cairosvg` depends on the native Cairo runtime on Windows.
- On this machine, `pip install cairosvg` was attempted twice and timed out while
  resolving/downloading `cairosvg`/`cairocffi` metadata, so this round stops
  environment work and does not use a preview renderer fallback.

Next options:
1. Use `cairosvg` plus a system Cairo DLL/runtime installed and discoverable on
   Windows.
2. Use a standalone `resvg` executable and call it from the PNG exporter.

Until one option is selected and verified, SVG/DXF are the production handoff
formats. Generated `order.json` records `metadata.pngExport.status = "skipped"`
with the reason.
