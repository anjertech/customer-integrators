#!/usr/bin/env python3
"""
Fetch GMUni payment data from Oracle databases and send to payments endpoint.

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
  python fetch_and_send_gmuni_payments.py --password YOUR_PASSWORD
  python fetch_and_send_gmuni_payments.py --password YOUR_PASSWORD --db P_CUALE_KIA_LINDAVISTA
  python fetch_and_send_gmuni_payments.py --password YOUR_PASSWORD --dry-run --verbose
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp
import oracledb
import requests

from gmuni_mappings import build_organization_id
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
SAME_ORDER_PAYMENT_DELAY_SECONDS = 2.0
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


class PaymentProgressTracker:
    """Tracks sent payment IDs for safe retries and resumable runs."""

    def __init__(self, db_name: str) -> None:
        self.db_name = db_name
        self.filename = f"progress_payments_{db_name}_live.json"
        self.data = self._load()

    def _load(self) -> Dict[str, List[str]]:
        try:
            with open(self.filename, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                payments = data.get("payments", [])
                print(
                    f"Loaded progress from {self.filename} (payments sent: {len(payments)})"
                )
                return {"payments": payments}
        except FileNotFoundError:
            return {"payments": []}
        except Exception:
            return {"payments": []}

    def _save(self) -> None:
        with open(self.filename, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle)

    def is_sent(self, payment_id: str) -> bool:
        return payment_id in self.data["payments"]

    def mark_sent(self, payment_id: str) -> None:
        if payment_id not in self.data["payments"]:
            self.data["payments"].append(payment_id)
            self._save()


# =============================================================================
# SQL QUERY
# =============================================================================

PAYMENTS_QUERY_BASE = """
SELECT
    EMPR_CVENASA,
    PRIM_DOCUMENTO,
    SECU_REGLON,
    SECU_TIPO,
    SECU_FECHAEMISION,
    ENRE_PREFIJO,
    ENRE_FOLIO,
    SECU_DOCUMENTO,
    ENRE_FECHA,
    CVE_FORMAPAGO,
    DESCRIP_FORMAPAGO,
    CVE_INST_MONETARIO,
    DESCRIP_INST_MONETARIO,
    MONEDA_PAGO,
    SECU_IMPORTE,
    EMPR_EMPRESAID,
    ENRE_CONCEPTO,
    ENRE_MONTOPAGO,
    ENRE_IVA,
    ENRE_MONE_TIPO,
    ENRE_FPAG_CLAVE,
    FPAG_DESCRIP,
    FPAG_FORMAXML,
    ENRE_STATUS,
    ENRE_TIPO_CLAVECANC,
    ENRE_POLI_FOLIOCANC,
    ENRE_POLI_FECHACANC,
    FECHAALTA,
    FECHA_MOVIMIENTO,
    ORIGEN,
    AGEN_IDAGENCIA,
    EMPR_DESCRMARCA,
    AGEN_NOMAGENCIA,
    AGEN_IDENTIFICADORFI,
    SECU_REFERENCIA1,
    SECU_REFERENCIA2,
    SECU_REFERENCIA3
FROM autos.CC_VRECIBOS_SECU_PLD_CARONE
"""


def default_from_date_ymd() -> str:
    today = datetime.now()
    year = today.year if today.month >= 5 else today.year - 1
    return f"{year}-05-01"


def build_query(from_date: Optional[str] = None, to_date: Optional[str] = None) -> str:
    query = PAYMENTS_QUERY_BASE
    conditions: List[str] = []

    if from_date is None:
        from_date = default_from_date_ymd()
        print(f"Using default from_date: {from_date} (since May)")

    if from_date:
        conditions.append(
            f"SECU_FECHAEMISION >= TO_DATE('{from_date}', 'YYYY-MM-DD')"
        )
    if to_date:
        conditions.append(
            f"SECU_FECHAEMISION < TO_DATE('{to_date}', 'YYYY-MM-DD') + 1"
        )

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY SECU_FECHAEMISION DESC"
    return query


# =============================================================================
# HELPERS
# =============================================================================

DATE_FORMATS_WITH_TIME = [
    "%d-%b-%y %H:%M:%S",
    "%d/%m/%y %H:%M:%S",
    "%d-%m-%y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
]


def safe_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    parsed = str(value).strip()
    return parsed if parsed else None


def parse_amount(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = str(value).replace(",", "").replace('"', "").strip()
        if not parsed:
            return None
        return float(parsed)
    except Exception:
        return None


def parse_date_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat() + "Z"

    raw = str(value).strip().upper()
    if not raw:
        return None

    for fmt in DATE_FORMATS_WITH_TIME:
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.isoformat() + "Z"
        except ValueError:
            continue
    return None


def first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        parsed = safe_string(value)
        if parsed is not None:
            return parsed
    return None


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


SAT_TOKEN_RE = re.compile(r"\b\d{2}\b")


def first_sat_code(raw_value: Optional[str]) -> Optional[str]:
    if not raw_value:
        return None

    raw_value = raw_value.strip()
    if not raw_value:
        return None

    parts = re.split(r"[,|;/\s]+", raw_value)
    for part in parts:
        token = part.strip()
        if len(token) == 2 and token.isdigit():
            return token

    match = SAT_TOKEN_RE.search(raw_value)
    if match:
        return match.group(0)
    return None


FPAG_CLAVE_TO_FORMAXML: Dict[str, str] = {
    "TRC": "02",
    "TRE": "01",
    "EYT": "01,04",
    "EYD": "01,28",
    "CYE": "02,01",
    "ETR": "01,03",
    "EFE": "01",
    "TAR": "04",
    "TYE": "04,01",
    "TYT": "04,04",
    "CYB": "02,28",
    "TRA": "03",
    "RYR": "01,01",
    "CYR": "02,01",
    "TYR": "04,99",
    "EYR": "01,01",
    "REC": "01",
    "AER": "04,01",
    "TRR": "03,01",
    "TAD": "28",
    "TDD": "28,28",
    "TDE": "28,01",
    "TDR": "28,99",
    "AME": "04",
    "AET": "99,04",
    "TYB": "04,28",
    "ATD": "99,28",
    "AEE": "04,01",
    "CHE": "02",
    "CYC": "02,02",
    "TRB": "03,03",
    "CYT": "02,04",
    "COR": "99",
    "TRD": "03,28",
    "SUB": "13",
    "DDP": "12",
    "COM": "17",
    "MYE": "17,01",
    "MYT": "17,03",
}


def map_instrument_description_to_sat(description: Optional[str]) -> str:
    if not description:
        return "99"

    normalized = " ".join(description.split()).strip().upper()
    if not normalized:
        return "99"

    if len(normalized) == 2 and normalized.isdigit():
        return normalized

    direct_map = {
        "EFECTIVO": "01",
        "FICHA DEPOSITO EFECTIVO": "01",
        "CONTADO": "01",
        "FICHA DEPOSITO": "01",
        "CHEQUE": "02",
        "FICHA CHEQUE": "02",
        "TRANSFERENCIA BANCARIA": "03",
        "TRANSFERENCIA": "03",
        "SPEI/TRANSFERENCIA": "03",
        "DESEMBOLSO MARCA": "03",
        "TARJETA BANORTE": "04",
        "TARJETA BANREGIO": "04",
        "TARJETA BBVA": "04",
        "TARJETA BANAMEX": "04",
        "TARJETA AMERICAN EXPRESS": "04",
        "TARJETA SANTANDER": "04",
        "TARJETA": "04",
        "ANTICIPO": "30",
        "EGRESO DE ANTICIPO": "30",
        "CREDITO": "99",
        "TOMA DE UNIDAD": "99",
        "RECIBO": "99",
        "SUBROGACION": "13",
        "DACION": "12",
        "COMPENSACION": "17",
    }

    return direct_map.get(normalized, "99")


def resolve_payment_form(row: Dict[str, Any]) -> str:
    # 1) Prefer explicit FPAG_FORMAXML
    sat_from_xml = first_sat_code(safe_string(row.get("FPAG_FORMAXML")))
    if sat_from_xml:
        return sat_from_xml

    # 2) Try code-based mapping from ENRE_FPAG_CLAVE / CVE_FORMAPAGO
    fpag_clave = normalize_text(row.get("ENRE_FPAG_CLAVE"))
    if fpag_clave in FPAG_CLAVE_TO_FORMAXML:
        mapped = first_sat_code(FPAG_CLAVE_TO_FORMAXML[fpag_clave])
        if mapped:
            return mapped

    cve_formapago = normalize_text(row.get("CVE_FORMAPAGO"))
    if cve_formapago in FPAG_CLAVE_TO_FORMAXML:
        mapped = first_sat_code(FPAG_CLAVE_TO_FORMAXML[cve_formapago])
        if mapped:
            return mapped

    # 3) Try instrument key if it's already SAT code
    cve_inst = safe_string(row.get("CVE_INST_MONETARIO"))
    if cve_inst:
        sat_from_inst = first_sat_code(cve_inst)
        if sat_from_inst:
            return sat_from_inst

    # 4) Fallback to descriptions
    for description in (
        safe_string(row.get("DESCRIP_INST_MONETARIO")),
        safe_string(row.get("FPAG_DESCRIP")),
        safe_string(row.get("DESCRIP_FORMAPAGO")),
    ):
        sat = map_instrument_description_to_sat(description)
        if sat != "99":
            return sat

    return "99"


def derive_cfdi_type(payment_form: str) -> str:
    return "credit_note" if payment_form == "30" else "payment_receipt"


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


def payment_id_from_reglon(value: Any) -> Optional[str]:
    raw = safe_string(value)
    if raw is None:
        return None

    compact = raw.replace(",", "")
    if re.fullmatch(r"\d+(\.0+)?", compact):
        return compact.split(".", 1)[0]

    return compact


def has_cancellation_markers(row: Dict[str, Any]) -> bool:
    return any(
        safe_string(row.get(field))
        for field in ("ENRE_TIPO_CLAVECANC", "ENRE_POLI_FOLIOCANC", "ENRE_POLI_FECHACANC")
    )


def has_master_send_override(row: Dict[str, Any]) -> bool:
    return normalize_text(row.get("ORIGEN")) in {"07 NCRE", "20 OTROS"}


def should_force_zero_pld_fields(row: Dict[str, Any]) -> bool:
    return normalize_text(row.get("ORIGEN")) == "20 OTROS"


def is_sendable_enre_status(status: str) -> bool:
    # Business rule: we should still send when ENRE_STATUS is empty or NO ENCONTRADO-like.
    if not status:
        return True
    if status == "AC":
        return True
    if status.startswith("NO ENCONTR") or status.startswith("NOT ENCONTR"):
        return True
    return False


def build_dedupe_key(row: Dict[str, Any]) -> Tuple[str, ...]:
    amount = parse_amount(row.get("SECU_IMPORTE"))
    amount_str = "" if amount is None else f"{amount:.4f}"
    dt = parse_date_iso(row.get("SECU_FECHAEMISION")) or ""
    return (
        normalize_text(row.get("PRIM_DOCUMENTO")),
        normalize_text(row.get("SECU_DOCUMENTO")),
        normalize_text(row.get("ENRE_PREFIJO")),
        normalize_text(row.get("ENRE_FOLIO")),
        normalize_text(row.get("SECU_REGLON")),
        amount_str,
        dt,
    )


def build_payment_payload(
    row: Dict[str, Any], _db_name: str, db_config: Dict[str, str]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    force_send = has_master_send_override(row)
    status = normalize_text(row.get("ENRE_STATUS"))
    if not force_send and not is_sendable_enre_status(status):
        return None, "inactive_status"

    if not force_send and has_cancellation_markers(row):
        return None, "cancelled_row"

    source_order_id = first_non_empty(row.get("PRIM_DOCUMENTO"), row.get("SECU_DOCUMENTO"))
    if source_order_id is None:
        return None, "missing_order_id"

    source_amount = parse_amount(row.get("SECU_IMPORTE"))
    if source_amount is None:
        return None, "invalid_amount"

    final_amount = round(-source_amount, 2)
    if abs(final_amount) < 0.01:
        return None, "zero_amount"

    payment_form = resolve_payment_form(row)
    cfdi_type = derive_cfdi_type(payment_form)

    # Keep organization generation aligned with fetch_and_send_gmuni:
    # same triplet shape (company_name--empresa_id--agencia_id),
    # preferring EMPR_NOMBRE when available.
    organization_name = first_non_empty(
        row.get("EMPR_NOMBRE"),
        db_config.get("group"),
        row.get("EMPR_DESCRMARCA"),
    )
    organization = build_organization_id(
        str(organization_name or ""),
        str(first_non_empty(row.get("EMPR_EMPRESAID")) or ""),
        str(first_non_empty(row.get("AGEN_IDAGENCIA")) or ""),
    )

    payment_id = payment_id_from_reglon(row.get("SECU_REGLON"))
    if payment_id is None:
        return None, "missing_payment_id"

    payload: Dict[str, Any] = {
        "id": payment_id,
        "salt": payment_id,
        "order_id": f"{source_order_id}|{source_order_id}",
        "organization": organization,
        "payment_form": payment_form,
        "payment_type": "internal",
        "cfdi_conceptual_type": cfdi_type,
        "amount": final_amount,
        "total": final_amount,
    }

    # Business rule: ORIGEN=20 OTROS must be sent with explicit PLD zero values.
    if should_force_zero_pld_fields(row):
        payload["pld_payment_form"] = "0"
        payload["pld_monetary_instrument"] = "0"

    payment_date = parse_date_iso(row.get("SECU_FECHAEMISION")) or parse_date_iso(
        row.get("ENRE_FECHA")
    )
    if payment_date:
        payload["date"] = payment_date

    operation_reference = first_non_empty(
        row.get("ENRE_CONCEPTO"),
        row.get("SECU_REFERENCIA1"),
        row.get("SECU_REFERENCIA2"),
        row.get("SECU_REFERENCIA3"),
    )
    if operation_reference:
        payload["operation_reference"] = operation_reference

    return payload, None


# =============================================================================
# DATABASE FETCH
# =============================================================================

def fetch_from_database(
    db_name: str,
    db_config: Dict[str, str],
    user: str,
    password: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    print(f"\n{'=' * 72}")
    print(f"Fetching payments from: {db_name} ({db_config['group']})")
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
# TRANSFORMATION
# =============================================================================

def transform_rows_to_payloads(
    rows: List[Dict[str, Any]],
    db_name: str,
    db_config: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    stats = {
        "total_rows": len(rows),
        "prepared": 0,
        "inactive_status": 0,
        "cancelled_row": 0,
        "missing_order_id": 0,
        "missing_payment_id": 0,
        "invalid_amount": 0,
        "zero_amount": 0,
        "duplicate": 0,
    }

    prepared: List[Dict[str, Any]] = []
    seen_keys: Set[Tuple[str, ...]] = set()

    for row in rows:
        key = build_dedupe_key(row)
        if key in seen_keys:
            stats["duplicate"] += 1
            continue
        seen_keys.add(key)

        payload, skip_reason = build_payment_payload(row, db_name, db_config)
        if payload is None:
            if skip_reason in stats:
                stats[skip_reason] += 1
            continue

        prepared.append(payload)
        stats["prepared"] += 1

    prepared.sort(
        key=lambda p: (p.get("order_id", ""), p.get("date", ""), p.get("id", ""))
    )
    return prepared, stats


def print_transform_stats(stats: Dict[str, int]) -> None:
    print("\nTransformation summary:")
    print(f"  Total rows:            {stats['total_rows']}")
    print(f"  Prepared payloads:     {stats['prepared']}")
    print(f"  Skipped inactive:      {stats['inactive_status']}")
    print(f"  Skipped cancelled:     {stats['cancelled_row']}")
    print(f"  Skipped missing order: {stats['missing_order_id']}")
    print(f"  Skipped missing id:    {stats['missing_payment_id']}")
    print(f"  Skipped bad amount:    {stats['invalid_amount']}")
    print(f"  Skipped zero amount:   {stats['zero_amount']}")
    print(f"  Skipped duplicates:    {stats['duplicate']}")


def apply_continue_from(
    payloads: List[Dict[str, Any]], continue_from: Optional[str]
) -> List[Dict[str, Any]]:
    if not continue_from:
        return payloads

    marker = continue_from
    if continue_from.startswith("payments-"):
        marker = continue_from.split("-", 1)[1]

    for idx, payload in enumerate(payloads):
        if payload.get("id") == marker:
            print(f"Continue-from marker found: {marker} (starting from this payment)")
            return payloads[idx:]

    print(f"Continue-from marker not found in payload set: {marker}")
    return payloads


# =============================================================================
# API SEND
# =============================================================================

async def send_batch(
    session: aiohttp.ClientSession,
    payments: List[Dict[str, Any]],
    batch_num: int,
    total_batches: int,
    token_manager: TokenManager,
    progress_tracker: PaymentProgressTracker,
    throttle_state: Dict[str, Any],
    verbose: bool = False,
) -> Dict[str, int]:
    print(
        f"Sending batch {batch_num}/{total_batches} to payments ({len(payments)} item(s))..."
    )

    stats = {"sent": 0, "skipped": 0, "errors": 0}

    for idx, payment in enumerate(payments, start=1):
        payment_id = payment.get("id", "<missing-id>")

        if progress_tracker.is_sent(payment_id):
            print(
                f"  [payments] Item {idx} (id={payment_id}): SKIPPED (already sent)"
            )
            stats["skipped"] += 1
            continue

        headers = token_manager.get_headers()
        if verbose:
            print(f"  [payments] Payload {idx}:\n{json.dumps(payment, indent=2)}")

        current_order_id = safe_string(payment.get("order_id"))
        last_order_id = throttle_state.get("last_order_id")
        last_post_ts = throttle_state.get("last_post_ts")
        if (
            current_order_id
            and current_order_id == last_order_id
            and isinstance(last_post_ts, float)
        ):
            elapsed = time.monotonic() - last_post_ts
            wait_seconds = SAME_ORDER_PAYMENT_DELAY_SECONDS - elapsed
            if wait_seconds > 0:
                print(
                    f"  [payments] Same order detected ({current_order_id}), "
                    f"waiting {wait_seconds:.2f}s before posting..."
                )
                await asyncio.sleep(wait_seconds)

        try:
            async with session.post(
                f"{API_BASE}/payments", headers=headers, json=payment
            ) as response:
                response_data = await response.json()
                print(
                    f"  [payments] Item {idx} (id={payment_id}): {response.status} - {response_data}"
                )
                response.raise_for_status()
                progress_tracker.mark_sent(payment_id)
                stats["sent"] += 1
        except Exception as exc:
            print(f"  [payments] Error on item {idx} (id={payment_id}): {exc}")
            stats["errors"] += 1
        finally:
            throttle_state["last_order_id"] = current_order_id
            throttle_state["last_post_ts"] = time.monotonic()

    return stats


async def send_payments_to_api(
    db_name: str,
    payments: List[Dict[str, Any]],
    batch_size: int,
    token_manager: TokenManager,
    verbose: bool = False,
) -> Dict[str, int]:
    progress_tracker = PaymentProgressTracker(db_name)
    token_manager.get_token()

    sent = 0
    skipped = 0
    errors = 0
    throttle_state: Dict[str, Any] = {"last_order_id": None, "last_post_ts": None}

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(payments), batch_size):
            batch = payments[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(payments) + batch_size - 1) // batch_size
            batch_stats = await send_batch(
                session=session,
                payments=batch,
                batch_num=batch_num,
                total_batches=total_batches,
                token_manager=token_manager,
                progress_tracker=progress_tracker,
                throttle_state=throttle_state,
                verbose=verbose,
            )
            sent += batch_stats["sent"]
            skipped += batch_stats["skipped"]
            errors += batch_stats["errors"]
            await asyncio.sleep(BATCH_DELAY_SECONDS)

    return {"sent": sent, "skipped": skipped, "errors": errors}


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch GMUni payments from Oracle and send to /payments"
    )
    parser.add_argument("--password", type=str, required=True, help="Oracle password")
    parser.add_argument("--user", type=str, default="PRESA", help="Oracle username")
    parser.add_argument("--db", type=str, help="Specific database to query (default: all)")
    parser.add_argument("--batch-size", type=int, default=5, help="API batch size")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no API calls")
    parser.add_argument("--list", action="store_true", help="List available databases")
    parser.add_argument(
        "--from-date",
        type=str,
        help="Filter payments from this date (YYYY-MM-DD) by SECU_FECHAEMISION",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        help="Filter payments up to this date (YYYY-MM-DD) by SECU_FECHAEMISION",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of payment payloads to send (global across selected DBs)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print payloads before sending")
    parser.add_argument(
        "--continue-from",
        type=str,
        help="Resume from payment ID (accepts raw id or 'payments-<id>')",
    )
    args = parser.parse_args()

    if args.list:
        print("Available databases:")
        for name, config in DATABASES.items():
            print(f"  {name} ({config['group']})")
        return 0

    print(f"\nUsing connection-manager tunnel at {LOCAL_TUNNEL_HOST}:{LOCAL_TUNNEL_PORT}")
    print("Make sure SSH tunnel is running:")
    print("  ssh -o PubkeyAuthentication=no -N \\")
    print("    -L 16223:192.168.10.88:6223 \\")
    print("    -L 16224:192.168.11.160:1521 \\")
    print("    -L 16225:192.168.11.173:1521 \\")
    print("    -L 16226:192.168.10.85:1521 \\")
    print("    PRESA@192.168.10.83")

    if args.db:
        if args.db not in DATABASES:
            print(f"Error: Unknown database '{args.db}'")
            print("Use --list to see available databases")
            return 1
        dbs_to_query = {args.db: DATABASES[args.db]}
    else:
        dbs_to_query = DATABASES

    token_manager = TokenManager()
    remaining_limit = args.limit
    grand_totals = {"prepared": 0, "sent": 0, "skipped": 0, "errors": 0}

    for db_name, db_config in dbs_to_query.items():
        if remaining_limit is not None and remaining_limit <= 0:
            break

        rows = fetch_from_database(
            db_name=db_name,
            db_config=db_config,
            user=args.user,
            password=args.password,
            from_date=args.from_date,
            to_date=args.to_date,
        )
        payloads, stats = transform_rows_to_payloads(rows, db_name, db_config)
        print_transform_stats(stats)

        payloads = apply_continue_from(payloads, args.continue_from)

        if remaining_limit is not None:
            payloads = payloads[:remaining_limit]
            remaining_limit -= len(payloads)

        grand_totals["prepared"] += len(payloads)
        print(f"\nPrepared payment payloads for {db_name}: {len(payloads)}")

        if args.dry_run:
            print("[DRY RUN] Skipping API calls")
            if payloads:
                print("\nSample payment payload:")
                print(json.dumps(payloads[0], indent=2, default=str))
            continue

        if not payloads:
            print("No payment payloads to send for this DB.")
            continue

        send_stats = asyncio.run(
            send_payments_to_api(
                db_name=db_name,
                payments=payloads,
                batch_size=args.batch_size,
                token_manager=token_manager,
                verbose=args.verbose,
            )
        )
        grand_totals["sent"] += send_stats["sent"]
        grand_totals["skipped"] += send_stats["skipped"]
        grand_totals["errors"] += send_stats["errors"]

        print(
            f"\nDB {db_name} send summary: sent={send_stats['sent']} "
            f"skipped={send_stats['skipped']} errors={send_stats['errors']}"
        )

    print("\n=== FINAL SUMMARY ===")
    print(f"Prepared payloads: {grand_totals['prepared']}")
    if not args.dry_run:
        print(f"Sent:             {grand_totals['sent']}")
        print(f"Skipped sent:     {grand_totals['skipped']}")
        print(f"Errors:           {grand_totals['errors']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
