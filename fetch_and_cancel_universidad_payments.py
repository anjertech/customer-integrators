#!/usr/bin/env python3
"""Fetch Universidad flattened sales rows and cancel payments for cancelled invoices."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Dict

from universidad_common import (
    add_api_args,
    add_source_args,
    build_payment_cancellation_targets,
    cancel_targets,
    load_source_rows,
    require_auth_args,
    TokenManager,
)


def print_prep_stats(stats: Dict[str, int]) -> None:
    print("\nCancellation preparation summary (payments):")
    print(f"  Source rows:           {stats['total_rows']}")
    print(f"  Active rows skipped:   {stats['active_rows']}")
    print(f"  Cancelled source rows: {stats['cancelled_rows']}")
    print(f"  Missing payment ID:    {stats['missing_payment_id']}")
    print(f"  Duplicate targets:     {stats['duplicate_target']}")
    print(f"  Prepared targets:      {stats['prepared']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Universidad rows and cancel payments through /payments/{id}/cancel"
    )
    add_source_args(parser, default_date_field="fechacanc")
    add_api_args(parser)
    parser.add_argument("--batch-size", type=int, default=10, help="Cancel API batch size")
    parser.add_argument("--dry-run", action="store_true", help="Prepare only, no API calls")
    parser.add_argument("--limit", type=int, help="Maximum number of cancellation targets")
    parser.add_argument("--verbose", action="store_true", help="Print per-target details")
    parser.add_argument("--db-key", default="universidad", help="Progress file key")
    args = parser.parse_args()

    try:
        rows = load_source_rows(args, default_date_field="fechacanc")
        targets, stats = build_payment_cancellation_targets(
            rows,
            organization_override=args.organization,
            organization_mode=args.organization_mode,
        )
        print_prep_stats(stats)

        if args.limit is not None:
            targets = targets[: args.limit]
            print(f"\nAfter --limit {args.limit}: targets={len(targets)}")

        if args.dry_run:
            print("\n[DRY RUN] Skipping cancellation API calls")
            if targets:
                print("\nSample cancellation target:")
                print(json.dumps(targets[0], indent=2))
            return 0

        require_auth_args(args)
        token_manager = TokenManager(
            api_base=args.api_base,
            tenant_id=args.tenant_id,
            client_id=args.client_id,
            client_secret=args.client_secret,
        )
        totals = asyncio.run(
            cancel_targets(
                api_base=args.api_base,
                token_manager=token_manager,
                db_key=args.db_key,
                endpoint="payments",
                targets=targets,
                batch_size=args.batch_size,
                verbose=args.verbose,
            )
        )
        print("\n=== PAYMENTS CANCELLATION COMPLETE ===")
        print(f"Cancelled: {totals['cancelled']}")
        print(f"Skipped:   {totals['skipped']}")
        print(f"Errors:    {totals['errors']}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
