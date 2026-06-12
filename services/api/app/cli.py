from __future__ import annotations

import argparse
import sys

from app.domain import DomainError
from app.domain.orders import generate_batch, import_orders, save_batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import-orders")
    import_parser.add_argument("--source", required=True)
    import_parser.add_argument("--adapter", choices=["dianxiaomi-xlsx", "generic-csv"])
    import_parser.add_argument("--batch-id")
    import_parser.add_argument("--default-listing-id", default="birth-flower-card")

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--batch-id", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "import-orders":
            batch = import_orders(
                args.source,
                adapter_name=args.adapter,
                batch_id=args.batch_id,
                default_listing_id=args.default_listing_id,
            )
            save_batch(batch)
            print(f"batchId={batch.batch_id}")
            print(f"adapter={batch.source_adapter}")
            print(f"orders={len(batch.items)}")
            return 0
        if args.command == "generate":
            result = generate_batch(args.batch_id)
            print(f"batchId={result.batch_id}")
            print(f"report={result.report_path}")
            print(f"reviewCsv={result.review_csv_path}")
            for item in result.items:
                paths = ";".join(item.output_paths)
                print(f"orderId={item.order_id} status={item.status} paths={paths}")
            return 0
    except DomainError as exc:
        print(f"error={exc.code} details={exc.details}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
