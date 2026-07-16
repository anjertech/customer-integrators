#!/usr/bin/env python3
"""
Test script for Oracle DB connections via SSH tunnel + SOURCE_ROUTE.

Prerequisites:
1. Install oracledb: pip install oracledb
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
  python test_oracle_connection.py                    # Test first DB only
  python test_oracle_connection.py --all              # Test all DBs
  python test_oracle_connection.py --db P_CUALE_KIA_LINDAVISTA  # Test specific DB
"""

import oracledb
import argparse
import sys
import os
from oracle_client import initialize_oracle_thick_mode

# Initialize thick mode for older Oracle DB servers
# This requires Oracle Instant Client to be installed
try:
    oracle_client_path = initialize_oracle_thick_mode()
    print(f"Using thick mode (Oracle Client at {oracle_client_path})")
except Exception as e:
    print(e, file=sys.stderr)
    sys.exit(1)

# All database configurations
# Key: TNS name, Value: internal Oracle host IP
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

# Connection defaults
LOCAL_TUNNEL_HOST = "127.0.0.1"
LOCAL_TUNNEL_PORT = 16223
SERVICE_NAME = "SISTEMAS"


def build_dsn(db_config: dict) -> str:
    """Build Oracle DSN string with SOURCE_ROUTE through tunnel."""
    host = db_config["host"]
    
    # Some DBs don't use SOURCE_ROUTE (commented out in tnsnames)
    if db_config.get("no_route"):
        port = db_config.get("direct_tunnel_port", LOCAL_TUNNEL_PORT)
        # Direct connection (still through tunnel for network access)
        return f"""(DESCRIPTION=
            (ADDRESS=(PROTOCOL=TCP)(HOST={LOCAL_TUNNEL_HOST})(PORT={port}))
            (CONNECT_DATA=(SERVICE_NAME={SERVICE_NAME}))
        )"""
    else:
        # SOURCE_ROUTE through connection manager
        return f"""(DESCRIPTION=
            (SOURCE_ROUTE=YES)
            (ADDRESS=(PROTOCOL=TCP)(HOST={LOCAL_TUNNEL_HOST})(PORT={LOCAL_TUNNEL_PORT}))
            (ADDRESS=(PROTOCOL=TCP)(HOST={host})(PORT=1521))
            (CONNECT_DATA=(SERVICE_NAME={SERVICE_NAME}))
        )"""


def test_connection(db_name: str, db_config: dict, user: str, password: str) -> bool:
    """Test connection to a single database."""
    print(f"\n{'='*60}")
    print(f"Testing: {db_name}")
    print(f"Group: {db_config['group']}")
    print(f"Host: {db_config['host']}")
    print(f"Route: {'Direct' if db_config.get('no_route') else 'SOURCE_ROUTE'}")
    print("-" * 60)
    
    dsn = build_dsn(db_config)
    
    try:
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        print(f"✓ Connected successfully!")
        
        # Test query
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        result = cursor.fetchone()
        print(f"✓ Test query (SELECT 1 FROM DUAL): {result[0]}")
        
        # Try to list some tables (optional)
        cursor.execute("""
            SELECT table_name FROM user_tables 
            WHERE ROWNUM <= 5
            ORDER BY table_name
        """)
        tables = [row[0] for row in cursor.fetchall()]
        if tables:
            print(f"✓ Sample tables: {', '.join(tables)}")
        
        cursor.close()
        conn.close()
        return True
        
    except oracledb.Error as e:
        print(f"✗ Connection failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test Oracle DB connections")
    parser.add_argument("--all", action="store_true", help="Test all databases")
    parser.add_argument("--db", type=str, help="Test specific database by name")
    parser.add_argument("--user", type=str, default="PRESA", help="Oracle username")
    parser.add_argument("--password", type=str, help="Oracle password")
    parser.add_argument("--list", action="store_true", help="List all available databases")
    args = parser.parse_args()
    
    if args.list:
        print("Available databases:")
        for name, config in DATABASES.items():
            print(f"  {name} ({config['group']})")
        return
    
    # Get password from arg, env, or prompt
    password = args.password or os.environ.get("ORACLE_PASSWORD")
    if not password:
        import getpass
        password = getpass.getpass(f"Enter password for {args.user}: ")
    
    print(f"\nUsing connection-manager tunnel at {LOCAL_TUNNEL_HOST}:{LOCAL_TUNNEL_PORT}")
    print("Make sure SSH tunnel is running:")
    print("  ssh -o PubkeyAuthentication=no -N \\")
    print("    -L 16223:192.168.10.88:6223 \\")
    print("    -L 16224:192.168.11.160:1521 \\")
    print("    -L 16225:192.168.11.173:1521 \\")
    print("    -L 16226:192.168.10.85:1521 \\")
    print("    PRESA@192.168.10.83")
    
    results = {}
    
    if args.db:
        # Test specific DB
        if args.db not in DATABASES:
            print(f"Error: Unknown database '{args.db}'")
            print("Use --list to see available databases")
            sys.exit(1)
        results[args.db] = test_connection(args.db, DATABASES[args.db], args.user, password)
    
    elif args.all:
        # Test all DBs
        for db_name, db_config in DATABASES.items():
            results[db_name] = test_connection(db_name, db_config, args.user, password)
    
    else:
        # Test first DB only (default)
        first_db = next(iter(DATABASES.items()))
        results[first_db[0]] = test_connection(first_db[0], first_db[1], args.user, password)
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print("=" * 60)
    success = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"Passed: {success}/{total}")
    
    if success < total:
        print("\nFailed databases:")
        for db_name, passed in results.items():
            if not passed:
                print(f"  - {db_name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
