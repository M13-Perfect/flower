# Desktop XLSX Import

`ui_app.py` keeps the legacy single-remark path for `.txt`, `.json`, and `.csv`
files through `order_importer.load_order_remark_from_file`.

For `.xlsx`, `ui_app.py` prepends `<project>/services/api` to `sys.path` at
runtime, then imports the backend domain modules directly:

1. `app.domain.orders.batch_import.import_orders(..., adapter_name="dianxiaomi-xlsx")`
2. `app.domain.orders.batch_store.save_batch(...)`
3. `app.domain.orders.batch_generate.generate_batch(...)`

This is a local `PYTHONPATH` wiring choice, not a FastAPI route call. The same
Python environment that launches `ui_app.py` must have the root requirements
installed, especially `openpyxl` for XLSX import and report writing:

```powershell
python -m pip install -r requirements.txt
```

The generated report is written by the API domain layer under
`outputs/reports/<batchId>-report.xlsx`; the desktop dialog shows the absolute
report path and provides an `打开报告` button.
