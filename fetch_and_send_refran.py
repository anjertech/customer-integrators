#!/usr/bin/env python3
"""
Fetch Refran SQL Server orders and send vehicles, customers, and orders via API.

This intentionally mirrors the active retail/exchange query path used by
core/local/uploaders/src/bin/refran/main_order_parser.rs, but it posts entities
through the Presa API instead of writing DynamoDB/S3 records directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

from refran_common import (
    RefranSqlServerSource,
    TokenManager,
    add_refran_api_args,
    add_refran_source_args,
    build_refran_order_entities,
    effective_from_date,
    parse_db_names,
    parse_transaction_types,
    require_auth_args,
    require_source_args,
    send_refran_entity_batches,
)


def print_transform_stats(stats: Dict[str, int]) -> None:
    print("\nTransformation summary (Refran orders):")
    print(f"  Target source orders:       {stats.get('target_orders', 0)}")
    print(f"  Prepared vehicles:          {stats.get('prepared_vehicles', 0)}")
    print(f"  Prepared customers:         {stats.get('prepared_customers', 0)}")
    print(f"  Prepared orders:            {stats.get('prepared_orders', 0)}")
    print(f"  Missing customer rows:      {stats.get('missing_customer_rows', 0)}")
    print(f"  Missing order rows:         {stats.get('missing_order_rows', 0)}")
    print(f"  Missing vehicle rows:       {stats.get('missing_vehicle_rows', 0)}")
    print(f"  Invalid customers:          {stats.get('invalid_customers', 0)}")
    print(f"  Invalid vehicles:           {stats.get('invalid_vehicles', 0)}")
    print(f"  Invalid orders:             {stats.get('invalid_orders', 0)}")
    print(f"  Duplicate orders skipped:   {stats.get('duplicate_orders', 0)}")
    print(f"  Extra multi-vehicle rows:   {stats.get('multi_vehicle_order_rows', 0)}")


def apply_order_limit(
    vehicles: List[Dict[str, Any]],
    customers: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
    limit: Optional[int],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    if limit is None:
        return vehicles, customers, orders

    limited_orders = orders[:limit]
    vehicle_keys = {
        (order.get("vehicle_id"), order.get("organization"))
        for order in limited_orders
    }
    customer_keys = {
        (order.get("customer_id"), order.get("organization"))
        for order in limited_orders
    }
    limited_vehicles = [
        vehicle
        for vehicle in vehicles
        if (vehicle.get("id"), vehicle.get("organization")) in vehicle_keys
    ]
    limited_customers = [
        customer
        for customer in customers
        if (customer.get("id"), customer.get("organization")) in customer_keys
    ]
    return limited_vehicles, limited_customers, limited_orders


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Refran retail/exchange orders from SQL Server and send them through the API"
    )
    add_refran_source_args(parser)
    add_refran_api_args(parser)
    parser.add_argument("--batch-size", type=int, default=5, help="API batch size")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no API calls")
    parser.add_argument("--limit", type=int, help="Maximum number of order payloads to send")
    parser.add_argument("--verbose", action="store_true", help="Print payloads before sending")
    parser.add_argument("--db-key", default="refran", help="Progress file key")
    args = parser.parse_args()

    try:
        require_source_args(args)
        db_names = parse_db_names(args.db)
        transaction_types = parse_transaction_types(args.transaction_types)
        from_date = effective_from_date(args)

        print(f"Databases: {', '.join(db_names)}")
        print(f"Transaction types: {', '.join(transaction_types)}")
        print(f"Date filter: {from_date or 'any'} to {args.to_date or 'any'}")

        source = RefranSqlServerSource(args.connection_string)
        vehicles, customers, orders, stats = build_refran_order_entities(
            source=source,
            db_names=db_names,
            transaction_types=transaction_types,
            organization_override=args.organization,
            from_date=from_date,
            to_date=args.to_date,
            source_limit=args.source_limit,
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
            send_refran_entity_batches(
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
