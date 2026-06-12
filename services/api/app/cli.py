from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.domain import DomainError
from app.domain.orders.workflow import (
    export_review_csv_file,
    generate_batch_outputs,
    import_orders_file,
    import_review_csv_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except DomainError as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                        "recoverable": exc.recoverable,
                    }
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_orders = subparsers.add_parser("import-orders")
    import_orders.add_argument("source_path", nargs="?", type=Path)
    import_orders.add_argument("--source", type=Path)
    import_orders.add_argument("--adapter", choices=["dianxiaomi-xlsx", "generic-csv"])
    import_orders.add_argument("--batch-id")
    import_orders.add_argument("--default-listing-id", default="birth-flower-card")
    import_orders.set_defaults(handler=_handle_import_orders)

    export_review = subparsers.add_parser("export-review")
    export_review.add_argument("batch_id_positional", nargs="?")
    export_review.add_argument("--batch-id")
    export_review.add_argument("--output", type=Path, default=None)
    export_review.set_defaults(handler=_handle_export_review)

    import_review = subparsers.add_parser("import-review")
    import_review.add_argument("filled_csv", nargs="?", type=Path)
    import_review.add_argument("--source", type=Path)
    import_review.set_defaults(handler=_handle_import_review)

    generate = subparsers.add_parser("generate")
    generate.add_argument("batch_id_positional", nargs="?")
    generate.add_argument("--batch-id")
    generate.add_argument("--png", action="store_true")
    generate.add_argument("--exported-at", default=None)
    generate.set_defaults(handler=_handle_generate)

    return parser


def _handle_import_orders(args: argparse.Namespace) -> dict:
    source = args.source or args.source_path
    if source is None:
        raise DomainError(
            code="CLI_ARGUMENT_MISSING",
            message="import-orders requires --source or a source path.",
            recoverable=True,
        )
    batch = import_orders_file(
        source,
        adapter_name=args.adapter,
        batch_id=args.batch_id,
        default_listing_id=args.default_listing_id,
    )
    return {
        "batchId": batch.batch_id,
        "adapter": batch.source_adapter,
        "summary": _summary(batch),
    }


def _handle_export_review(args: argparse.Namespace) -> dict:
    batch_id = _batch_id_arg(args)
    path = export_review_csv_file(batch_id, args.output)
    return {"batchId": batch_id, "path": path.as_posix()}


def _handle_import_review(args: argparse.Namespace) -> dict:
    source = args.source or args.filled_csv
    if source is None:
        raise DomainError(
            code="CLI_ARGUMENT_MISSING",
            message="import-review requires --source or a CSV path.",
            recoverable=True,
        )
    batch = import_review_csv_file(source)
    return {"batchId": batch.batch_id, "summary": _summary(batch)}


def _handle_generate(args: argparse.Namespace) -> dict:
    result = generate_batch_outputs(
        _batch_id_arg(args),
        include_png=True,
        exported_at=args.exported_at,
    )
    return {
        "batchId": result.batch_id,
        "generated": result.generated_count,
        "failed": result.failed_count,
        "items": [
            {
                "orderJobId": item.order_job_id,
                "orderId": item.order_id,
                "status": item.status,
                "outputDir": item.output_dir,
                "files": list(item.files),
                "error": item.error,
            }
            for item in result.items
        ],
    }


def _batch_id_arg(args: argparse.Namespace) -> str:
    batch_id = args.batch_id or args.batch_id_positional
    if not batch_id:
        raise DomainError(
            code="CLI_ARGUMENT_MISSING",
            message="Command requires --batch-id or a batch id argument.",
            recoverable=True,
        )
    return str(batch_id)


def _summary(batch) -> dict:
    return {
        "total": len(batch.items),
        "ready": sum(1 for item in batch.items if item.status == "READY"),
        "needsReview": sum(1 for item in batch.items if item.status == "NEEDS_REVIEW"),
        "blocked": sum(1 for item in batch.items if item.status == "BLOCKED"),
        "failed": sum(1 for item in batch.items if item.status == "FAILED"),
        "exported": sum(1 for item in batch.items if item.status == "EXPORTED"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
