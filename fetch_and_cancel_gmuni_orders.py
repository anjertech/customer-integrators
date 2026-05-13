#!/usr/bin/env python3
"""
Fetch GMUni order rows from Oracle and cancel non-AC orders through orders endpoint.

This is a separate process from fetch_and_send_gmuni.py.
It uses dedicated tracker files and only stores successfully cancelled items.

Prerequisites:
1. Install: pip install oracledb aiohttp requests
2. Start SSH tunnel:
   ssh -o PubkeyAuthentication=no -N \
     -L 16223:192.168.10.88:6223 \
     -L 16224:192.168.11.160:1521 \
     -L 16225:192.168.11.173:1521 \
     -L 16226:192.168.10.85:1521 \
     PRESA@192.168.10.83
3. Make Oracle Instant Client available to the script:
   export PRESA_ORACLE_CLIENT_DIR=/absolute/path/to/instantclient_23_3
   # or place it in ./instantclient_23_3 or ./vendor/oracle/instantclient_23_3

Usage examples:
  python fetch_and_cancel_gmuni_orders.py --password YOUR_PASSWORD
  python fetch_and_cancel_gmuni_orders.py --password YOUR_PASSWORD --db P_CUALE_KIA_LINDAVISTA
  python fetch_and_cancel_gmuni_orders.py --password YOUR_PASSWORD --dry-run --verbose
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import aiohttp
import oracledb
import requests

from gmuni_mappings import get_organization_from_row
from oracle_client import initialize_oracle_thick_mode


# =============================================================================
# ORACLE CLIENT SETUP
# =============================================================================

try:
    oracle_client_path = initialize_oracle_thick_mode()
    print(f"Using thick mode (Oracle Client at {oracle_client_path})")
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)


# =============================================================================
# DATABASE CONFIGURATIONS
# =============================================================================

DATABASES = {
    # CAR ONE AMERICANA
    "P_COAME_CHEVRO_UNIVERSIDAD": {"host": "192.168.11.46", "group": "CAR ONE AMERICANA"},
    "P_COAME_CHEVRO_RCORTINES": {"host": "192.168.10.33", "group": "CAR ONE AMERICANA"},
    "P_COAME_CHEVRO_NOGALAR": {"host": "192.168.11.160", "group": "CAR ONE AMERICANA", "no_route": True, "direct_tunnel_port": 16224},
    "P_COAME_CHEVRO_LASTORRES": {"host": "192.168.11.84", "group": "CAR ONE AMERICANA"},
    # CAR ONE VALLE
    "P_COVAL_FORD_VALLE": {"host": "192.168.11.164", "group": "CAR ONE VALLE"},
    # C1 ALEMANA
    "P_CUALE_KIA_FRONTERA": {"host": "192.168.11.173", "group": "C1 ALEMANA", "no_route": True, "direct_tunnel_port": 16225},
    "P_CUALE_KIA_GONZALITOS": {"host": "192.168.11.88", "group": "C1 ALEMANA"},
    "P_CUALE_KIA_LAREDO": {"host": "192.168.11.78", "group": "C1 ALEMANA"},
    "P_CUALE_KIA_LINDAVISTA": {"host": "192.168.11.41", "group": "C1 ALEMANA"},
    # CAR ONE TLALPAN
    "P_COTLA_CHEVRO_LASBOMBAS": {"host": "192.168.11.82", "group": "CAR ONE TLALPAN"},
    "P_COTLA_CHEVRO_TLALPAN": {"host": "192.168.11.38", "group": "CAR ONE TLALPAN"},
    # CAR ONE ORIENTAL
    "P_COORI_CHIREY_CHIREY": {"host": "192.168.11.253", "group": "CAR ONE ORIENTAL"},
    # CAR ONE MONTERREY
    "P_COMON_STELLA_CONTRY": {"host": "192.168.11.98", "group": "CAR ONE MONTERREY"},
    "P_COMON_STELLA_CUMBRES": {"host": "192.168.11.75", "group": "CAR ONE MONTERREY"},
    "P_COMON_STELLA_SLUCIA": {"host": "192.168.11.79", "group": "CAR ONE MONTERREY"},
    "P_COMON_MG_MG": {"host": "192.168.11.251", "group": "CAR ONE MONTERREY"},
    "P_COMON_JETOUR_JETOUR": {"host": "192.168.10.3", "group": "CAR ONE MONTERREY"},
    # CAR ONE CALZADA
    "P_COCAL_GEELY_GEELY": {"host": "192.168.10.13", "group": "CAR ONE CALZADA"},
    # CAR ONE MOTORS
    "P_COMOT_GWM_GWM": {"host": "192.168.10.16", "group": "CAR ONE MOTORS"},
    # CAR ONE NORESTE
    "P_CONOR_OMOD_CHIR_CHAN": {"host": "192.168.10.5", "group": "CAR ONE NORESTE"},
    # NISSAN SANJE
    "P_COSAN_NISSA_SANJE": {"host": "192.168.10.85", "group": "NISSAN SANJE", "no_route": True, "direct_tunnel_port": 16226},
}

LOCAL_TUNNEL_HOST = "127.0.0.1"
LOCAL_TUNNEL_PORT = 16223
SERVICE_NAME = "SISTEMAS"


# =============================================================================
# API CONFIGURATION
# =============================================================================

API_BASE = "https://api.presa.anjer.mx"
AUTH_CONFIG = {
    "url": f"{API_BASE}/auth/login",
    "tenant_id": "carone",
    "client_id": "carone",
    "client_secret": "83tta-Jvkal-Dtbc7-F1zHt",
}
TOKEN_REFRESH_SECONDS = 45 * 60
BATCH_DELAY_SECONDS = 0.25


class TokenManager:
    """Manages API auth token with periodic refresh."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_time: Optional[float] = None

    def get_token(self) -> str:
        now = time.time()
        if (
            self._token is None
            or self._token_time is None
            or (now - self._token_time) > TOKEN_REFRESH_SECONDS
        ):
            self._refresh_token()
        return self._token

    def _refresh_token(self) -> None:
        print("\nFetching fresh auth token...")
        response = requests.post(
            AUTH_CONFIG["url"],
            headers={
                "tenant_id": AUTH_CONFIG["tenant_id"],
                "tenant": AUTH_CONFIG["tenant_id"],
            },
            json={
                "client_id": AUTH_CONFIG["client_id"],
                "client_secret": AUTH_CONFIG["client_secret"],
            },
            timeout=30,
        )
        data = response.json()
        if data.get("status_code") != 200:
            raise RuntimeError(f"Auth failed: {data}")

        self._token = data["data"]["token"]
        self._token_time = time.time()
        print(
            f"✓ Got token (expires in {data['data']['expires_in']}s, refresh in {TOKEN_REFRESH_SECONDS}s)"
        )

    def get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": self.get_token(),
        }


class CancellationTracker:
    """Tracks successfully cancelled route IDs for safe retries and resumable runs."""

    def __init__(self, db_name: str) -> None:
        self.filename = f"progress_cancel_orders_{db_name}_live.json"
        self.data = self._load()

    def _load(self) -> Dict[str, List[str]]:
        try:
            with open(self.filename, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                cancelled = data.get("cancelled", [])
                print(
                    f"Loaded cancellation progress from {self.filename} (cancelled: {len(cancelled)})"
                )
                return {"cancelled": cancelled}
        except FileNotFoundError:
            return {"cancelled": []}
        except Exception:
            return {"cancelled": []}

    def _save(self) -> None:
        with open(self.filename, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle)

    def is_cancelled(self, route_id: str) -> bool:
        return route_id in self.data["cancelled"]

    def mark_cancelled(self, route_id: str) -> None:
        if route_id not in self.data["cancelled"]:
            self.data["cancelled"].append(route_id)
            self._save()


# =============================================================================
# SQL QUERY
# =============================================================================

ORDERS_QUERY_BASE = """
SELECT
    FAAU_NOFACTURA,
    FAAU_STATUS,
    FAAU_FECHA,
    EMPR_NOMBRE,
    EMPR_EMPRESAID,
    AGEN_IDAGENCIA
FROM autos.VT_VFACTURAS_PLD_CARONE
"""


def default_from_date_ymd() -> str:
    today = datetime.now()
    year = today.year if today.month >= 5 else today.year - 1
    return f"{year}-05-01"


def build_query(from_date: Optional[str] = None, to_date: Optional[str] = None) -> str:
    query = ORDERS_QUERY_BASE
    conditions: List[str] = []

    if from_date is None:
        from_date = default_from_date_ymd()
        print(f"Using default from_date: {from_date} (since May)")

    if from_date:
        conditions.append(f"FAAU_FECHA >= TO_DATE('{from_date}', 'YYYY-MM-DD')")
    if to_date:
        conditions.append(f"FAAU_FECHA < TO_DATE('{to_date}', 'YYYY-MM-DD') + 1")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY FAAU_FECHA DESC"
    return query


# =============================================================================
# HELPERS
# =============================================================================


def safe_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    parsed = str(value).strip()
    return parsed if parsed else None


def normalize_status(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def normalize_organization(organization: str) -> str:
    compact = (organization or "").strip()
    if not compact or compact.replace("-", "") == "":
        return "none"
    return compact


def build_order_route_id(row: Dict[str, Any]) -> Optional[str]:
    order_id = safe_string(row.get("FAAU_NOFACTURA"))
    if not order_id:
        return None

    organization = normalize_organization(get_organization_from_row(row))
    return f"{order_id}|{order_id}~{organization}"


# =============================================================================
# DATABASE FETCH
# =============================================================================


def build_dsn(db_config: Dict[str, str]) -> str:
    host = db_config["host"]

    if db_config.get("no_route"):
        port = db_config.get("direct_tunnel_port", LOCAL_TUNNEL_PORT)
        return f"""(DESCRIPTION=
            (ADDRESS=(PROTOCOL=TCP)(HOST={LOCAL_TUNNEL_HOST})(PORT={port}))
            (CONNECT_DATA=(SERVICE_NAME={SERVICE_NAME}))
        )"""

    return f"""(DESCRIPTION=
        (SOURCE_ROUTE=YES)
        (ADDRESS=(PROTOCOL=TCP)(HOST={LOCAL_TUNNEL_HOST})(PORT={LOCAL_TUNNEL_PORT}))
        (ADDRESS=(PROTOCOL=TCP)(HOST={host})(PORT=1521))
        (CONNECT_DATA=(SERVICE_NAME={SERVICE_NAME}))
    )"""


def fetch_from_database(
    db_name: str,
    db_config: Dict[str, str],
    user: str,
    password: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    print(f"\n{'=' * 72}")
    print(f"Fetching order statuses from: {db_name} ({db_config['group']})")
    if from_date or to_date:
        print(f"Date filter: {from_date or 'default'} -> {to_date or 'any'}")
    print("-" * 72)

    dsn = build_dsn(db_config)
    query = build_query(from_date, to_date)
    rows: List[Dict[str, Any]] = []

    try:
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        for row in cursor:
            rows.append(dict(zip(columns, row)))
        print(f"✓ Fetched {len(rows)} row(s)")
        cursor.close()
        conn.close()
    except oracledb.Error as exc:
        print(f"✗ Database error: {exc}")

    return rows


# =============================================================================
# CANCELLATION PREP
# =============================================================================


def build_cancellation_targets(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    stats = {
        "total_rows": len(rows),
        "active_ac": 0,
        "non_ac": 0,
        "missing_order_id": 0,
        "duplicate_target": 0,
        "prepared": 0,
    }

    targets: List[Dict[str, str]] = []
    seen: set[str] = set()

    for row in rows:
        status = normalize_status(row.get("FAAU_STATUS"))
        if status == "AC":
            stats["active_ac"] += 1
            continue

        stats["non_ac"] += 1

        route_id = build_order_route_id(row)
        if route_id is None:
            stats["missing_order_id"] += 1
            continue

        if route_id in seen:
            stats["duplicate_target"] += 1
            continue

        seen.add(route_id)
        targets.append(
            {
                "route_id": route_id,
                "status": status or "<empty>",
                "order_id": safe_string(row.get("FAAU_NOFACTURA")) or "",
            }
        )
        stats["prepared"] += 1

    return targets, stats


def print_prep_stats(stats: Dict[str, int]) -> None:
    print("\nCancellation preparation summary (orders):")
    print(f"  Total rows:           {stats['total_rows']}")
    print(f"  AC rows skipped:      {stats['active_ac']}")
    print(f"  Non-AC source rows:   {stats['non_ac']}")
    print(f"  Missing order ID:     {stats['missing_order_id']}")
    print(f"  Duplicate targets:    {stats['duplicate_target']}")
    print(f"  Prepared cancellations:{stats['prepared']}")


def apply_continue_from(
    targets: List[Dict[str, str]], continue_from: Optional[str]
) -> List[Dict[str, str]]:
    if not continue_from:
        return targets

    marker = continue_from
    if continue_from.startswith("orders-cancel-"):
        marker = continue_from.split("orders-cancel-", 1)[1]

    for idx, target in enumerate(targets):
        if target.get("route_id") == marker or target.get("order_id") == marker:
            print(f"Continue-from marker found: {marker} (starting from this target)")
            return targets[idx:]

    print(f"Continue-from marker not found in target set: {marker}")
    return targets


# =============================================================================
# API SEND
# =============================================================================


async def send_cancel_batch(
    session: aiohttp.ClientSession,
    targets: List[Dict[str, str]],
    batch_num: int,
    total_batches: int,
    token_manager: TokenManager,
    tracker: CancellationTracker,
    verbose: bool = False,
) -> Dict[str, int]:
    print(
        f"Sending cancel batch {batch_num}/{total_batches} to orders ({len(targets)} item(s))..."
    )

    stats = {"cancelled": 0, "skipped_tracker": 0, "errors": 0}

    for idx, target in enumerate(targets, start=1):
        route_id = target["route_id"]

        if tracker.is_cancelled(route_id):
            print(
                f"  [orders-cancel] Item {idx} (route_id={route_id}): SKIPPED (already cancelled)"
            )
            stats["skipped_tracker"] += 1
            continue

        headers = token_manager.get_headers()
        encoded_id = quote(route_id, safe="")
        url = f"{API_BASE}/orders/{encoded_id}/cancel"

        if verbose:
            print(
                f"  [orders-cancel] Item {idx}: route_id={route_id}, status={target.get('status')}"
            )

        try:
            async with session.post(url, headers=headers, json={}) as response:
                text = await response.text()
                try:
                    response_data = json.loads(text)
                except Exception:
                    response_data = text

                print(
                    f"  [orders-cancel] Item {idx} (route_id={route_id}): "
                    f"{response.status} - {response_data}"
                )

                response.raise_for_status()
                tracker.mark_cancelled(route_id)
                stats["cancelled"] += 1
        except Exception as exc:
            print(f"  [orders-cancel] Error on item {idx} (route_id={route_id}): {exc}")
            stats["errors"] += 1

    return stats


async def cancel_orders(
    db_name: str,
    targets: List[Dict[str, str]],
    batch_size: int,
    token_manager: TokenManager,
    verbose: bool = False,
) -> Dict[str, int]:
    tracker = CancellationTracker(db_name)
    token_manager.get_token()

    cancelled = 0
    skipped_tracker = 0
    errors = 0

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(targets), batch_size):
            batch = targets[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(targets) + batch_size - 1) // batch_size
            batch_stats = await send_cancel_batch(
                session=session,
                targets=batch,
                batch_num=batch_num,
                total_batches=total_batches,
                token_manager=token_manager,
                tracker=tracker,
                verbose=verbose,
            )
            cancelled += batch_stats["cancelled"]
            skipped_tracker += batch_stats["skipped_tracker"]
            errors += batch_stats["errors"]
            await asyncio.sleep(BATCH_DELAY_SECONDS)

    return {
        "cancelled": cancelled,
        "skipped_tracker": skipped_tracker,
        "errors": errors,
    }


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch GMUni orders from Oracle and cancel non-AC orders via /orders/{id}/cancel"
    )
    parser.add_argument("--password", type=str, required=True, help="Oracle password")
    parser.add_argument("--user", type=str, default="PRESA", help="Oracle username")
    parser.add_argument("--db", type=str, help="Specific database to query (default: all)")
    parser.add_argument("--batch-size", type=int, default=10, help="Cancel API batch size")
    parser.add_argument("--dry-run", action="store_true", help="Prepare only, no API calls")
    parser.add_argument("--list", action="store_true", help="List available databases")
    parser.add_argument(
        "--from-date",
        type=str,
        help="Filter orders from this date (YYYY-MM-DD) by FAAU_FECHA",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        help="Filter orders up to this date (YYYY-MM-DD) by FAAU_FECHA",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of cancellation targets per database",
    )
    parser.add_argument("--verbose", action="store_true", help="Print per-item details")
    parser.add_argument(
        "--continue-from",
        type=str,
        help="Resume from route_id or order_id (also accepts prefix 'orders-cancel-')",
    )

    args = parser.parse_args()

    if args.list:
        print("\nAvailable databases:")
        for db_name, config in DATABASES.items():
            print(f"  {db_name:<35} ({config['group']})")
        return 0

    if args.db:
        if args.db not in DATABASES:
            print(f"Error: Unknown database '{args.db}'")
            print("Use --list to see available databases")
            return 1
        dbs_to_query = {args.db: DATABASES[args.db]}
    else:
        dbs_to_query = DATABASES

    token_manager = TokenManager()

    grand_totals = {
        "prepared": 0,
        "cancelled": 0,
        "skipped_tracker": 0,
        "errors": 0,
    }

    for db_name, db_config in dbs_to_query.items():
        rows = fetch_from_database(
            db_name=db_name,
            db_config=db_config,
            user=args.user,
            password=args.password,
            from_date=args.from_date,
            to_date=args.to_date,
        )

        targets, prep_stats = build_cancellation_targets(rows)
        print_prep_stats(prep_stats)

        targets = apply_continue_from(targets, args.continue_from)

        if args.limit is not None:
            targets = targets[: args.limit]
            print(f"Applying --limit {args.limit}: {len(targets)} cancellation target(s)")

        grand_totals["prepared"] += len(targets)

        if args.dry_run:
            print("\n[DRY RUN] Skipping cancellation API calls")
            if targets:
                print("Sample cancellation target:")
                print(json.dumps(targets[0], indent=2))
            continue

        if not targets:
            print("No cancellation targets for this DB.")
            continue

        send_stats = asyncio.run(
            cancel_orders(
                db_name=db_name,
                targets=targets,
                batch_size=args.batch_size,
                token_manager=token_manager,
                verbose=args.verbose,
            )
        )

        grand_totals["cancelled"] += send_stats["cancelled"]
        grand_totals["skipped_tracker"] += send_stats["skipped_tracker"]
        grand_totals["errors"] += send_stats["errors"]

        print(
            f"\nDB {db_name}: cancelled={send_stats['cancelled']} "
            f"skipped_tracker={send_stats['skipped_tracker']} errors={send_stats['errors']}"
        )

    print("\n=== ORDERS CANCELLATION COMPLETE ===")
    print(f"Prepared targets:   {grand_totals['prepared']}")
    print(f"Cancelled:          {grand_totals['cancelled']}")
    print(f"Skipped (tracker):  {grand_totals['skipped_tracker']}")
    print(f"Errors:             {grand_totals['errors']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
