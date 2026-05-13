#!/usr/bin/env python3
"""
Fetch Universidad flattened sales rows and send vehicles, customers, and orders.

Source rows must expose the columns seen in VENTAS UNIVERSIDAD.xlsx. The source can
be a SQL Server table/view through ODBC or the workbook itself for dry-runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List

from universidad_common import (
    add_api_args,
    add_source_args,
    build_order_entities,
    load_source_rows,
    require_auth_args,
    send_entity_batches,
    TokenManager,
)


def print_transform_stats(stats: Dict[str, int]) -> None:
    print("\nTransformation summary (orders):")
    print(f"  Source rows:        {stats['total_rows']}")
    print(f"  Cancelled rows:     {stats['cancelled_rows']}")
    print(f"  Skipped cancelled:  {stats['skipped_cancelled']}")
    print(f"  Missing vehicles:   {stats['missing_vehicle']}")
    print(f"  Missing customers:  {stats['missing_customer']}")
    print(f"  Missing orders:     {stats['missing_order']}")
    print(f"  Vehicles prepared:  {stats['vehicles']}")
    print(f"  Customers prepared: {stats['customers']}")
    print(f"  Orders prepared:    {stats['orders']}")


def apply_order_limit(
    vehicles: List[Dict[str, Any]],
    customers: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
    limit: int | None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    if limit is None:
        return vehicles, customers, orders

    limited_orders = orders[:limit]
    vehicle_ids = {order.get("vehicle_id") for order in limited_orders}
    customer_ids = {order.get("customer_id") for order in limited_orders}
    limited_vehicles = [vehicle for vehicle in vehicles if vehicle.get("id") in vehicle_ids]
    limited_customers = [customer for customer in customers if customer.get("id") in customer_ids]
    return limited_vehicles, limited_customers, limited_orders


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Universidad flattened sales rows and send vehicles/customers/orders"
    )
    add_source_args(parser, default_date_field="FechaFact")
    add_api_args(parser)
    parser.add_argument("--batch-size", type=int, default=5, help="API batch size")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no API calls")
    parser.add_argument("--include-cancelled", action="store_true", help="Include rows with Cancelacion/fechacanc")
    parser.add_argument("--limit", type=int, help="Maximum number of order payloads to send")
    parser.add_argument("--verbose", action="store_true", help="Print payloads before sending")
    parser.add_argument("--db-key", default="universidad", help="Progress file key")
    args = parser.parse_args()

    try:
        rows = load_source_rows(args, default_date_field="FechaFact")
        vehicles, customers, orders, stats = build_order_entities(
            rows,
            organization_override=args.organization,
            organization_mode=args.organization_mode,
            include_cancelled=args.include_cancelled,
        )
        print_transform_stats(stats)

        vehicles, customers, orders = apply_order_limit(vehicles, customers, orders, args.limit)
        if args.limit is not None:
            print(f"\nAfter --limit {args.limit}:")
            print(f"  Vehicles:  {len(vehicles)}")
            print(f"  Customers: {len(customers)}")
            print(f"  Orders:    {len(orders)}")

        if args.dry_run:
            print("\n[DRY RUN] Skipping API calls")
            if vehicles:
                print("\nSample vehicle:")
                print(json.dumps(vehicles[0], indent=2, default=str))
            if customers:
                print("\nSample customer:")
                print(json.dumps(customers[0], indent=2, default=str))
            if orders:
                print("\nSample order:")
                print(json.dumps(orders[0], indent=2, default=str))
            return 0

        require_auth_args(args)
        token_manager = TokenManager(
            api_base=args.api_base,
            tenant_id=args.tenant_id,
            client_id=args.client_id,
            client_secret=args.client_secret,
        )
        totals = asyncio.run(
            send_entity_batches(
                api_base=args.api_base,
                token_manager=token_manager,
                db_key=args.db_key,
                vehicles=vehicles,
                customers=customers,
                orders=orders,
                batch_size=args.batch_size,
                verbose=args.verbose,
            )
        )
        print("\n=== FINAL SUMMARY ===")
        for endpoint, endpoint_stats in totals.items():
            print(
                f"{endpoint}: sent={endpoint_stats['sent']} "
                f"skipped={endpoint_stats['skipped']} errors={endpoint_stats['errors']}"
            )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
