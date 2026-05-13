#!/usr/bin/env python3
"""
Fetch Universidad flattened sales rows and send payments.

The workbook/source table has order and payment data in one row. Payment IDs are
derived as uuidPago-Factura so one shared payment CFDI can be applied to multiple
orders without colliding in the API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Dict

from universidad_common import (
    add_api_args,
    add_source_args,
    build_payment_payloads,
    load_source_rows,
    require_auth_args,
    send_payment_batches,
    TokenManager,
)


def print_transform_stats(stats: Dict[str, int]) -> None:
    print("\nTransformation summary (payments):")
    print(f"  Source rows:          {stats['total_rows']}")
    print(f"  Cancelled rows:       {stats['cancelled_rows']}")
    print(f"  Skipped cancelled:    {stats['skipped_cancelled']}")
    print(f"  Prepared payloads:    {stats['prepared']}")
    print(f"  Missing order ID:     {stats['missing_order_id']}")
    print(f"  Missing payment ID:   {stats['missing_payment_id']}")
    print(f"  Invalid amount:       {stats['invalid_amount']}")
    print(f"  Zero amount:          {stats['zero_amount']}")
    print(f"  Duplicate payloads:   {stats['duplicate']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Universidad flattened sales rows and send payments"
    )
    add_source_args(parser, default_date_field="fechaTimbrePago")
    add_api_args(parser)
    parser.add_argument("--batch-size", type=int, default=5, help="API batch size")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no API calls")
    parser.add_argument("--include-cancelled", action="store_true", help="Include rows with Cancelacion/fechacanc")
    parser.add_argument("--limit", type=int, help="Maximum number of payment payloads to send")
    parser.add_argument("--verbose", action="store_true", help="Print payloads before sending")
    parser.add_argument("--db-key", default="universidad", help="Progress file key")
    args = parser.parse_args()

    try:
        rows = load_source_rows(args, default_date_field="fechaTimbrePago")
        payments, stats = build_payment_payloads(
            rows,
            organization_override=args.organization,
            organization_mode=args.organization_mode,
            include_cancelled=args.include_cancelled,
        )
        print_transform_stats(stats)

        if args.limit is not None:
            payments = payments[: args.limit]
            print(f"\nAfter --limit {args.limit}: payments={len(payments)}")

        if args.dry_run:
            print("\n[DRY RUN] Skipping API calls")
            if payments:
                print("\nSample payment:")
                print(json.dumps(payments[0], indent=2, default=str))
            return 0

        require_auth_args(args)
        token_manager = TokenManager(
            api_base=args.api_base,
            tenant_id=args.tenant_id,
            client_id=args.client_id,
            client_secret=args.client_secret,
        )
        totals = asyncio.run(
            send_payment_batches(
                api_base=args.api_base,
                token_manager=token_manager,
                db_key=args.db_key,
                payments=payments,
                batch_size=args.batch_size,
                verbose=args.verbose,
            )
        )
        print("\n=== FINAL SUMMARY ===")
        print(f"Sent:     {totals['sent']}")
        print(f"Skipped:  {totals['skipped']}")
        print(f"Errors:   {totals['errors']}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
