#!/usr/bin/env python3
"""
One-time script: fetch distinct GMUni sellers from Oracle and set seller account names via API.

Prerequisites:
1. Install deps: pip install oracledb requests
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

Usage:
  python fetch_and_send_gmuni_seller_names.py --password YOUR_PASSWORD
  python fetch_and_send_gmuni_seller_names.py --password YOUR_PASSWORD --db P_CUALE_KIA_LINDAVISTA
  python fetch_and_send_gmuni_seller_names.py --password YOUR_PASSWORD --dry-run
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import oracledb
import requests

from oracle_client import initialize_oracle_thick_mode


# =============================================================================
# ORACLE CLIENT SETUP
# =============================================================================

try:
    oracle_client_path = initialize_oracle_thick_mode()
    print(f"Using thick mode (Oracle Client at {oracle_client_path})")
except Exception as e:
    print(e, file=sys.stderr)
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
# API CONFIG
# =============================================================================

API_BASE = "https://api.presa.anjer.mx"
AUTH_CONFIG = {
    "url": f"{API_BASE}/auth/login",
    "tenant_id": "carone",
    "client_id": "carone",
    "client_secret": "83tta-Jvkal-Dtbc7-F1zHt",
}
TOKEN_REFRESH_SECONDS = 45 * 60


class TokenManager:
    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_time: Optional[float] = None

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
        expires_in = data["data"].get("expires_in")
        print(f"✓ Got token (expires in {expires_in}s, will refresh in {TOKEN_REFRESH_SECONDS}s)")

    def get_token(self) -> str:
        now = time.time()
        if (
            self._token is None
            or self._token_time is None
            or (now - self._token_time) > TOKEN_REFRESH_SECONDS
        ):
            self._refresh_token()
        return self._token

    def get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": self.get_token(),
        }


token_manager = TokenManager()


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class SellerRecord:
    seller_id: str
    name: Optional[str]
    paternal: Optional[str]
    maternal: Optional[str]
    email: Optional[str]
    empresa_id: Optional[str]
    agencia_id: Optional[str]
    source_query: str

    def completeness(self) -> int:
        score = 0
        if self.name:
            score += 1
        if self.paternal:
            score += 1
        if self.maternal:
            score += 1
        return score


class ProgressTracker:
    def __init__(self, run_name: str):
        safe_name = run_name.replace("/", "_")
        self.filename = f"progress_seller_names_{safe_name}_live.json"
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                    sellers = data.get("sellers", [])
                    print(f"Loaded progress from {self.filename} (sellers sent: {len(sellers)})")
                    return {"sellers": sellers}
            except Exception:
                pass
        return {"sellers": []}

    def _save(self) -> None:
        with open(self.filename, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2)

    def is_sent(self, seller_id: str) -> bool:
        return seller_id in self.data["sellers"]

    def mark_sent(self, seller_id: str) -> None:
        if seller_id not in self.data["sellers"]:
            self.data["sellers"].append(seller_id)
            self._save()


# =============================================================================
# SQL QUERIES
# =============================================================================

QUERY_CANDIDATES: List[Tuple[str, str, int]] = [
    (
        "autos_vt_vendedores",
        """
        SELECT DISTINCT
            EMPRESAID,
            IDAGENCIA,
            CLAVE,
            NOMBRE,
            APELLIDOPATERNO,
            APELLIDOMATERNO,
            TELEFONO,
            EMAIL,
            NONOMINA
        FROM autos.VT_VENDEDORES
        """,
        3,
    ),
    (
        "vt_vendedores",
        """
        SELECT DISTINCT
            EMPRESAID,
            IDAGENCIA,
            CLAVE,
            NOMBRE,
            APELLIDOPATERNO,
            APELLIDOMATERNO,
            TELEFONO,
            EMAIL,
            NONOMINA
        FROM VT_VENDEDORES
        """,
        3,
    ),
    (
        "autos_vfacturas_fallback",
        """
        SELECT DISTINCT
            EMPR_EMPRESAID AS EMPRESAID,
            AGEN_IDAGENCIA AS IDAGENCIA,
            FAAU_VEND_CLAVE AS CLAVE,
            VEND_NOMBRE AS NOMBRE_COMPLETO,
            VEND_EMAIL AS EMAIL,
            VEND_NONOMINA AS NONOMINA
        FROM autos.VT_VFACTURAS_PLD_CARONE
        WHERE FAAU_VEND_CLAVE IS NOT NULL
        """,
        2,
    ),
    (
        "vfacturas_fallback",
        """
        SELECT DISTINCT
            EMPR_EMPRESAID AS EMPRESAID,
            AGEN_IDAGENCIA AS IDAGENCIA,
            FAAU_VEND_CLAVE AS CLAVE,
            VEND_NOMBRE AS NOMBRE_COMPLETO,
            VEND_EMAIL AS EMAIL,
            VEND_NONOMINA AS NONOMINA
        FROM VT_VFACTURAS_PLD_CARONE
        WHERE FAAU_VEND_CLAVE IS NOT NULL
        """,
        2,
    ),
]


def build_dsn(db_config: Dict[str, Any]) -> str:
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


# =============================================================================
# HELPERS
# =============================================================================


def safe_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def parse_full_name(full_name: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not full_name:
        return None, None, None

    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return None, None, None
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        return parts[0], parts[1], None

    # Keep first names grouped and split last 2 tokens as paternal/maternal
    name = " ".join(parts[:-2])
    paternal = parts[-2]
    maternal = parts[-1]
    return name, paternal, maternal


def row_to_seller_record(row: Dict[str, Any], source_query: str) -> Optional[SellerRecord]:
    seller_id = safe_string(row.get("CLAVE")) or safe_string(row.get("NONOMINA"))
    if not seller_id:
        return None

    nombre = safe_string(row.get("NOMBRE"))
    paterno = safe_string(row.get("APELLIDOPATERNO"))
    materno = safe_string(row.get("APELLIDOMATERNO"))

    if not (nombre or paterno or materno):
        full_name = safe_string(row.get("NOMBRE_COMPLETO")) or safe_string(row.get("VEND_NOMBRE"))
        nombre, paterno, materno = parse_full_name(full_name)

    if not (nombre or paterno or materno):
        return None

    return SellerRecord(
        seller_id=seller_id,
        name=nombre,
        paternal=paterno,
        maternal=materno,
        email=safe_string(row.get("EMAIL")),
        empresa_id=safe_string(row.get("EMPRESAID")),
        agencia_id=safe_string(row.get("IDAGENCIA")),
        source_query=source_query,
    )


def choose_better_record(current: SellerRecord, incoming: SellerRecord) -> SellerRecord:
    # Prefer record with more complete name; on tie keep current.
    if incoming.completeness() > current.completeness():
        return incoming
    return current


# =============================================================================
# ORACLE FETCH
# =============================================================================


def fetch_sellers_from_database(
    db_name: str,
    db_config: Dict[str, Any],
    user: str,
    password: str,
) -> List[SellerRecord]:
    print(f"\n{'=' * 60}")
    print(f"Fetching sellers from: {db_name} ({db_config['group']})")
    print("-" * 60)

    dsn = build_dsn(db_config)

    try:
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
    except oracledb.Error as e:
        print(f"✗ Connection error for {db_name}: {e}")
        return []

    cursor = None
    try:
        cursor = conn.cursor()
        rows: List[Dict[str, Any]] = []
        query_label_used: Optional[str] = None

        for query_label, query, _priority in QUERY_CANDIDATES:
            try:
                cursor.execute(query)
                columns = [col[0] for col in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor]
                query_label_used = query_label
                print(f"✓ Query '{query_label}' worked ({len(rows)} rows)")
                break
            except oracledb.Error as query_err:
                print(f"  - Query '{query_label}' failed: {query_err}")

        if not rows or query_label_used is None:
            print("✗ No query candidate worked for this DB")
            return []

        sellers: List[SellerRecord] = []
        for row in rows:
            seller = row_to_seller_record(row, query_label_used)
            if seller is not None:
                sellers.append(seller)

        print(f"✓ Parsed sellers with non-empty name+id: {len(sellers)}")
        return sellers

    finally:
        try:
            if cursor is not None:
                cursor.close()
        except Exception:
            pass
        conn.close()


# =============================================================================
# API SEND
# =============================================================================


def send_seller_name(
    seller: SellerRecord,
    method: str,
    endpoint_suffix: str,
) -> Tuple[bool, int, Any]:
    seller_id_encoded = quote(seller.seller_id, safe="")
    url = f"{API_BASE}/seller-accounts/{seller_id_encoded}/{endpoint_suffix}"

    payload = {
        "name": {
            "name": seller.name,
            "paternal": seller.paternal,
            "maternal": seller.maternal,
        }
    }

    response = requests.request(
        method=method,
        url=url,
        headers=token_manager.get_headers(),
        json=payload,
        timeout=30,
    )

    try:
        data = response.json()
    except Exception:
        data = response.text

    ok = 200 <= response.status_code < 300
    return ok, response.status_code, data


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch distinct GMUni sellers and set seller account names in API"
    )
    parser.add_argument("--password", type=str, required=True, help="Oracle password")
    parser.add_argument("--user", type=str, default="PRESA", help="Oracle username")
    parser.add_argument("--db", type=str, help="Specific database to query (default: all)")
    parser.add_argument("--list", action="store_true", help="List available databases")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not call API")
    parser.add_argument("--limit", type=int, help="Send only first N distinct sellers")
    parser.add_argument(
        "--method",
        type=str,
        default="POST",
        choices=["POST", "PATCH", "PUT"],
        help="HTTP method for endpoint",
    )
    parser.add_argument(
        "--endpoint-suffix",
        type=str,
        default="add-name",
        help="Endpoint suffix after /seller-accounts/{id}/ (default: add-name)",
    )
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=150,
        help="Sleep between API requests in milliseconds",
    )
    args = parser.parse_args()
    args.endpoint_suffix = args.endpoint_suffix.strip("/")

    if args.list:
        print("Available databases:")
        for name, config in DATABASES.items():
            print(f"  {name:<35} ({config['group']})")
        return

    if args.db:
        if args.db not in DATABASES:
            print(f"Error: Unknown database '{args.db}'")
            print("Use --list to see available databases")
            sys.exit(1)
        dbs_to_query = {args.db: DATABASES[args.db]}
        run_name = args.db
    else:
        dbs_to_query = DATABASES
        run_name = "all_dbs"

    print(f"\nUsing connection-manager tunnel at {LOCAL_TUNNEL_HOST}:{LOCAL_TUNNEL_PORT}")
    print("Make sure SSH tunnel is running:")
    print("  ssh -o PubkeyAuthentication=no -N \\")
    print("    -L 16223:192.168.10.88:6223 \\")
    print("    -L 16224:192.168.11.160:1521 \\")
    print("    -L 16225:192.168.11.173:1521 \\")
    print("    -L 16226:192.168.10.85:1521 \\")
    print("    PRESA@192.168.10.83")

    all_sellers: List[SellerRecord] = []
    for db_name, db_config in dbs_to_query.items():
        sellers = fetch_sellers_from_database(db_name, db_config, args.user, args.password)
        print(f"DB {db_name}: fetched {len(sellers)} seller rows")
        all_sellers.extend(sellers)

    if not all_sellers:
        print("\nNo sellers found. Nothing to do.")
        return

    deduped: Dict[str, SellerRecord] = {}
    conflicts = 0

    for seller in all_sellers:
        current = deduped.get(seller.seller_id)
        if current is None:
            deduped[seller.seller_id] = seller
            continue

        candidate = choose_better_record(current, seller)
        if (
            current.name != seller.name
            or current.paternal != seller.paternal
            or current.maternal != seller.maternal
        ):
            conflicts += 1
        deduped[seller.seller_id] = candidate

    sellers_to_send = list(deduped.values())

    if args.limit:
        sellers_to_send = sellers_to_send[: args.limit]

    print(f"\n{'=' * 60}")
    print(f"Total rows fetched: {len(all_sellers)}")
    print(f"Distinct sellers by id: {len(deduped)}")
    print(f"Name conflicts detected while deduping: {conflicts}")
    print(f"Selected for this run: {len(sellers_to_send)}")
    print("=" * 60)

    if sellers_to_send:
        sample = sellers_to_send[0]
        sample_payload = {
            "id": sample.seller_id,
            "name": {
                "name": sample.name,
                "paternal": sample.paternal,
                "maternal": sample.maternal,
            },
            "empresa_id": sample.empresa_id,
            "agencia_id": sample.agencia_id,
            "source_query": sample.source_query,
        }
        print("\nSample payload:")
        print(json.dumps(sample_payload, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("\n[DRY RUN] Skipping API calls")
        return

    progress_tracker = ProgressTracker(run_name)

    # Warm token early
    token_manager.get_token()

    sent = 0
    skipped = 0
    errors = 0

    for idx, seller in enumerate(sellers_to_send, start=1):
        if progress_tracker.is_sent(seller.seller_id):
            skipped += 1
            print(f"[{idx}/{len(sellers_to_send)}] seller_id={seller.seller_id}: SKIPPED (already sent)")
            continue

        try:
            ok, status, response_data = send_seller_name(
                seller=seller,
                method=args.method,
                endpoint_suffix=args.endpoint_suffix,
            )
        except Exception as e:
            errors += 1
            print(f"[{idx}/{len(sellers_to_send)}] seller_id={seller.seller_id}: ERROR {e}")
            continue

        if ok:
            sent += 1
            progress_tracker.mark_sent(seller.seller_id)
            print(f"[{idx}/{len(sellers_to_send)}] seller_id={seller.seller_id}: {status} OK")
        else:
            errors += 1
            print(
                f"[{idx}/{len(sellers_to_send)}] seller_id={seller.seller_id}: "
                f"{status} ERROR {response_data}"
            )

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    print("\n=== SEND SUMMARY ===")
    print(f"Sent: {sent}")
    print(f"Skipped: {skipped}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
