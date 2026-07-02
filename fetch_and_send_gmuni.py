#!/usr/bin/env python3
"""
Fetch GMUni data from Oracle databases and send to API.

Prerequisites:
1. Install: pip install oracledb aiohttp
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
  python fetch_and_send_gmuni.py --password YOUR_PASSWORD                    # All DBs
  python fetch_and_send_gmuni.py --password YOUR_PASSWORD --db P_CUALE_KIA_LINDAVISTA  # Single DB
  python fetch_and_send_gmuni.py --password YOUR_PASSWORD --dry-run          # Parse only, no API calls
"""

import oracledb
import aiohttp
import asyncio
import argparse
import sys
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import quote

from gmuni_mappings import (
    get_organization_from_row,
    map_order_types_from_row,
    get_order_status,
)
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

# Connection defaults
LOCAL_TUNNEL_HOST = "127.0.0.1"
LOCAL_TUNNEL_PORT = 16223
SERVICE_NAME = "SISTEMAS"

# API Configuration
API_BASE = "https://api.presa.anjer.mx"
AUTH_CONFIG = {
    "url": f"{API_BASE}/auth/login",
    "tenant_id": "carone",
    "client_id": "carone",
    "client_secret": "83tta-Jvkal-Dtbc7-F1zHt"
}
TOKEN_REFRESH_SECONDS = 45 * 60  # Refresh token every 45 minutes
# Retries for order POST right after dependency recovery (eventual consistency).
ORDER_RECOVERY_RETRY_DELAYS = [0.0, 0.75, 1.5]


class TokenManager:
    """Manages auth token with auto-refresh."""
    
    def __init__(self):
        self._token = None
        self._token_time = None
    
    def get_token(self) -> str:
        """Get current token, refreshing if needed."""
        import time
        
        now = time.time()
        
        # Refresh if no token or token is older than 45 minutes
        if self._token is None or (now - self._token_time) > TOKEN_REFRESH_SECONDS:
            self._refresh_token()
        
        return self._token
    
    def _refresh_token(self):
        """Fetch fresh auth token from API."""
        import requests
        import time
        
        print("\nFetching fresh auth token...")
        
        response = requests.post(
            AUTH_CONFIG["url"],
            headers={
                "tenant_id": AUTH_CONFIG["tenant_id"],
                "tenant": AUTH_CONFIG["tenant_id"],
            },
            json={
                "client_id": AUTH_CONFIG["client_id"],
                "client_secret": AUTH_CONFIG["client_secret"]
            }
        )
        
        data = response.json()
        if data.get("status_code") != 200:
            raise Exception(f"Auth failed: {data}")
        
        self._token = data["data"]["token"]
        self._token_time = time.time()
        expires_in = data["data"]["expires_in"]
        print(f"✓ Got token (expires in {expires_in}s, will refresh in {TOKEN_REFRESH_SECONDS}s)")
    
    def get_headers(self) -> dict:
        """Build request headers with current auth token."""
        return {
            "Content-Type": "application/json",
            "Authorization": self.get_token()
        }


# Global token manager instance
token_manager = TokenManager()


class ProgressTracker:
    """Tracks sent IDs to a JSON file for resuming after failures."""
    
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.filename = f"progress_{db_name}_live.json"
        self.data = self._load()
    
    def _load(self) -> dict:
        """Load existing progress or create new."""
        import json
        import os
        
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    data = json.load(f)
                    print(f"Loaded progress from {self.filename}")
                    print(f"  Vehicles sent: {len(data.get('vehicles', []))}")
                    print(f"  Customers sent: {len(data.get('customers', []))}")
                    print(f"  Orders sent: {len(data.get('orders', []))}")
                    return data
            except:
                pass
        
        return {'vehicles': [], 'customers': [], 'orders': []}
    
    def _save(self):
        """Save progress to file."""
        import json
        with open(self.filename, 'w') as f:
            json.dump(self.data, f)
    
    def mark_sent(self, entity_type: str, entity_id: str):
        """Mark an entity as successfully sent."""
        if entity_id not in self.data[entity_type]:
            self.data[entity_type].append(entity_id)
            self._save()
    
    def is_sent(self, entity_type: str, entity_id: str) -> bool:
        """Check if an entity was already sent."""
        return entity_id in self.data[entity_type]
    
    def get_stats(self) -> dict:
        """Get current progress stats."""
        return {
            'vehicles': len(self.data['vehicles']),
            'customers': len(self.data['customers']),
            'orders': len(self.data['orders'])
        }


# Global progress tracker (initialized per DB)
progress_tracker: Optional[ProgressTracker] = None


def scoped_customer_key(customer_id: Any, organization: Any) -> str:
    """Build the sender-side customer key used for GMUNI org-scoped customers."""
    customer_id = safe_string(customer_id)
    organization = safe_string(organization) or "none"
    if not customer_id:
        return ""
    return f"{customer_id}~{organization}"


def customer_payload_key(customer: Dict[str, Any]) -> str:
    """Build the sender-side key for a parsed customer payload."""
    return scoped_customer_key(customer.get("id"), customer.get("organization"))


def order_customer_payload_key(order: Dict[str, Any]) -> str:
    """Build the sender-side customer key required by a parsed order payload."""
    return scoped_customer_key(order.get("customer_id"), order.get("organization"))


def progress_entity_id(endpoint: str, item: Dict[str, Any]) -> Optional[str]:
    """
    Progress files must distinguish GMUNI customers with the same id in different
    organizations. Other endpoints keep the legacy id-only progress key.
    """
    if endpoint == "customers":
        return customer_payload_key(item) or None
    return item.get("id")


def backend_lookup_endpoint(endpoint: str) -> Optional[str]:
    if endpoint in {"customers", "orders"}:
        return endpoint
    return None


async def _backend_item_exists(
    session: aiohttp.ClientSession,
    endpoint: str,
    item: Dict[str, Any],
) -> Dict[str, Any]:
    lookup_endpoint = backend_lookup_endpoint(endpoint)
    item_id = safe_string(item.get("id"))
    if not lookup_endpoint or not item_id:
        return {"checked": False, "exists": None, "status": None, "response_data": None}

    params = {}
    organization = safe_string(item.get("organization"))
    if organization:
        params["organization"] = organization

    url = f"{API_BASE}/{lookup_endpoint}/{quote(item_id, safe='')}"
    try:
        async with session.get(url, headers=token_manager.get_headers(), params=params) as response:
            try:
                response_data = await response.json(content_type=None)
            except Exception:
                response_data = await response.text()
            if response.status == 200:
                return {"checked": True, "exists": True, "status": response.status, "response_data": response_data}
            if response.status == 404:
                return {"checked": True, "exists": False, "status": response.status, "response_data": response_data}
            return {"checked": True, "exists": None, "status": response.status, "response_data": response_data}
    except Exception as exc:
        return {"checked": True, "exists": None, "status": None, "response_data": str(exc)}

# =============================================================================
# SQL QUERY
# =============================================================================

QUERY_BASE = """
SELECT
    AGEN_NOMBRE_SUCURSAL, TIPOMOV, TIPO_AVISO, FECHAMOV, FAAU_STATUS,
    EST_PLD_RPT, EST_PLD_FISCAL, FOLIO_AVISO, FECHA_AVISO, FECHA_AVISOACUM,
    FAAU_NOFACTURA, FAAU_FECHA, FAAU_FECHACANCELACION, FAAU_CLIE_CLAVE,
    FAAU_RAZONFACTURA, BASE_ISAN, FAAU_IVA, FAAU_ISAN, FAAU_TOTAL, PRIM_SALDO,
    PRIM_UUIDS, FAAU_FORM_TIPOVENTA, FORM_AGRUPACIONVENTAS, PRIM_FOLIO,
    PRIM_DOCUMENTO, ULT_FECH_PAGO, ID_ACUMULA, COMPLETO, MES_REPORTADO,
    CLAVE_ENTIDAD_COLEGIADA, CLAVE_SUJETO_OBLIGADO, CLAVE_ACTIVIDAD, EXENTO,
    REFERENCIA_AVISO, MODIFICATORIO, FOLIO_MODIFICACION, DESCRIPCION_MODIFICACION,
    PRIORIDAD, TIPO_ALERTA_CVE, DESCRIPCION_ALERTA, CVE_TIPO_PERSONA,
    CLIE_NOMBRE, CLIE_APELLIDOPATERNO, CLIE_APELLIDOMATERNO, CLIE_RAZONSOCIAL,
    CLIE_FECHANACIMIENTO, CLIE_FECHACONSTITUCION, FAAU_RFCFACTURA, CLIE_CURP,
    CLIE_NACIONALIDAD, CVE_ACTI_ECON_PF, CVE_ACTI_ECON_PM, REF_FIDEICOMISO,
    CLIE_NOMBREREPLEGAL, CLIE_APELLIDOPATERNOREPLEG, CLIE_APELLIDOMATERNOREPLEG,
    CLIE_FECHANACIMIENTOREPLEG, CLIE_RFCREPLEGAL, CLIE_CURPREPLEGAL,
    TIPO_DOMICILIO, CVEPAIS_DOM, EDOS_NOMBRE, MUNI_NOMBRE, FAAU_COLONIA,
    FAAU_DOMICILIOFACTURA, FAAU_NUMEXT, FAAU_NUMINT, FAAU_CP, CVEPAIS,
    CLIE_TELEFONO1, CLIE_EMAIL, TIPO_PERSONA_D_B, CLIE_NOMBRED_B,
    CLIE_APELLIDOPATERNOD_B, CLIE_APELLIDOMATERNOD_B, CLIE_RAZONSOCIALDD_B,
    CLIE_FECHANACIMIENTOD_B, CLIE_FECHACONSTITUCIOND_B, CLIE_RFCD_B,
    CLIE_CURPD_B, CLIE_NACIONALIDADD_B, CLIE_REFERENCIAD_B, FECHA_LIQUIDACION,
    AGEN_CP_AGENCIA, TIPO_OPERACION, AGEN_EDOS_NOMBRE, AGEN_MUNI_NOMBRE,
    AGEN_COLONIA, TIPO_VEHICULO, MARC_DESCRIP, MODE_DESCRIPCION, FAAU_VEHI_ANIO,
    VEHI_SERIE, VEHI_CVEREPUVE, PLACAS, NUM_SERIE, BANDERA, MATRICULA,
    VEHI_CVE_NIVELBLINDAJE, ULT_DOCUMENTO, ULT_TIPOMOV, U_REFERENCIA1,
    TOTALRECIBOS, DMS, EMPR_CVENASA, AGEN_AGENCIA, ORIGEN, FAAU_ID,
    FAAU_FORMAPAGO, FORM_GRUPODEVENTADIR, FORM_DESCRIPCION,
    FAAU_DELEGACIONFACTURA, FAAU_VEND_CLAVE, VEND_NOMCORTO, VEND_NOMBRE,
    FAAU_POLI_TIPOCLAVE, FAAU_POLI_FOLIO, FAAU_POLI_FECHA, PEDI_TIPO_CLAVECANC,
    PEDI_POLI_FOLIOCANC, PEDI_POLI_FECHACANC, FAAU_VEHI_NUMEROINVENTARIO,
    FAAU_SERIE, FAAU_FOLIO, FAAU_FOLIOCAN_EGRE, FAAU_SERIECAN_EGRE,
    FAAU_UUIDCAN_EGRE, VEHI_FECHAENTREGA, VEHI_CVEVEHICULAR, PRIM_TIPOMOV,
    DOC_IDEN, DOC_CURP, DOC_RFC, DOC_DOMICILIO, DOC_CONTRATO, DOC_PAGO,
    DOC_AMDA, DOC_DB, DOC_ACTA, DOC_RIDEN, DOC_RCURP, DOC_RRFC, DOC_RPODER,
    DOC_GLOBAL, DOC_CARTA, DOC_LISTAS, DOC_EXPE_UNICO, PERIODO,
    FORM_ARTUS_AGRUPAVTA, VEHI_CLASE, FAAU_VEHI_CLASE, LARGORFC, VEND_NONOMINA,
    EMPR_EMPRESAID, EMPR_DESCRMARCA, AGEN_IDAGENCIA, AGEN_IDENTIFICADORFI,
    EMPR_NOMBRE, VEND_STATUS, VEND_EMAIL
FROM autos.VT_VFACTURAS_PLD_CARONE
"""


def default_from_date_ymd() -> str:
    today = datetime.now()
    year = today.year - 1
    return f"{year}-05-01"


def build_query(from_date: Optional[str] = None, to_date: Optional[str] = None) -> str:
    """Build query with optional date filters on FAAU_FECHA."""

    query = QUERY_BASE
    conditions = []

    # Default to May 1 if no from_date specified.
    if from_date is None:
        from_date = default_from_date_ymd()
        print(f"Using default from_date: {from_date} (since May)")

    if from_date:
        conditions.append(f"FAAU_FECHA >= TO_DATE('{from_date}', 'YYYY-MM-DD')")
    if to_date:
        conditions.append(f"FAAU_FECHA <= TO_DATE('{to_date}', 'YYYY-MM-DD')")
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    # Order by most recent first
    query += " ORDER BY FAAU_FECHA DESC"
    
    return query

# =============================================================================
# DATE PARSING
# =============================================================================

DATE_FORMATS_WITH_TIME = [
    "%d-%b-%y %H:%M:%S",  # 28-NOV-25 19:48:02
    "%d/%m/%y %H:%M:%S",  # 30/09/25 14:46:03
    "%d-%m-%y %H:%M:%S",  # 30-09-25 14:46:03
    "%Y-%m-%d %H:%M:%S",  # 2025-09-30 14:46:03
]

DATE_FORMATS_SIMPLE = [
    "%d-%b-%y",           # 28-NOV-25
    "%d/%m/%y",           # 30/09/25
    "%d-%m-%y",           # 30-09-25
    "%Y-%m-%d",           # 2025-09-30
]


def parse_date(date_val) -> Optional[str]:
    """Parse date with time to ISO format"""
    if date_val is None:
        return None
    
    # If it's already a datetime object from Oracle
    if isinstance(date_val, datetime):
        return date_val.isoformat() + "Z"
    
    date_str = str(date_val).strip().upper()
    if not date_str:
        return None
    
    for fmt in DATE_FORMATS_WITH_TIME:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.isoformat() + "Z"
        except ValueError:
            continue
    
    return None


def parse_simple_date(date_val) -> Optional[str]:
    """Parse simple date format to YYYY-MM-DD"""
    if date_val is None:
        return None
    
    # If it's already a datetime object from Oracle
    if isinstance(date_val, datetime):
        return date_val.strftime("%Y-%m-%d")
    
    date_str = str(date_val).strip().upper()
    if not date_str:
        return None
    
    for fmt in DATE_FORMATS_SIMPLE:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return None


# =============================================================================
# VALUE HELPERS
# =============================================================================

def safe_float(value) -> float:
    """Safely convert value to float"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except:
        return 0.0


def safe_string(value) -> Optional[str]:
    """Return None if empty, otherwise strip and return"""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def get_field(row: Dict[str, Any], field: str) -> Any:
    """Get field value from row dict"""
    return row.get(field) or row.get(f'EXP_{field}')


# =============================================================================
# ENTITY PARSING
# =============================================================================

def parse_vehicle(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse vehicle data from row"""
    vin = safe_string(get_field(row, 'VEHI_SERIE'))
    
    if not vin:
        return None
    
    return {
        "id": vin,
        "brand": safe_string(get_field(row, 'MARC_DESCRIP')),
        "model": safe_string(get_field(row, 'MODE_DESCRIPCION')),
        "vin": vin,
        "year": safe_string(get_field(row, 'FAAU_VEHI_ANIO')),
        "inventory_number": safe_string(get_field(row, 'FAAU_VEHI_NUMEROINVENTARIO')),
    }


def parse_customer(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse customer data from row"""
    customer_id = safe_string(get_field(row, 'FAAU_CLIE_CLAVE'))
    person_type = safe_string(get_field(row, 'CVE_TIPO_PERSONA'))
    
    if not customer_id:
        return None
    
    customer = {
        "id": customer_id,
        "organization": get_organization_from_row(row),
    }
    
    # Address
    address = {}
    street = safe_string(get_field(row, 'FAAU_DOMICILIOFACTURA'))
    number = safe_string(get_field(row, 'FAAU_NUMEXT'))
    int_number = safe_string(get_field(row, 'FAAU_NUMINT'))
    neighborhood = safe_string(get_field(row, 'FAAU_COLONIA'))
    city = safe_string(get_field(row, 'MUNI_NOMBRE'))
    state = safe_string(get_field(row, 'EDOS_NOMBRE'))
    postal_code = safe_string(get_field(row, 'FAAU_CP'))
    
    if street:
        address['street'] = street
    if number:
        address['number'] = number
    if int_number:
        address['int_number'] = int_number
    if neighborhood:
        address['neighborhood'] = neighborhood
    if city:
        address['city'] = city
    if state:
        address['state'] = state
    if postal_code:
        address['postal_code'] = postal_code
    address['country'] = 'MX'
    
    if address:
        customer['address'] = address
    
    # Phone
    phone_number = safe_string(get_field(row, 'CLIE_TELEFONO1'))
    if phone_number:
        customer['phone'] = {
            "country_code": "52",
            "number": phone_number
        }
    
    # Email
    email = safe_string(get_field(row, 'CLIE_EMAIL'))
    if email:
        customer['email'] = email
    
    # RFC
    rfc = safe_string(get_field(row, 'FAAU_RFCFACTURA'))
    if rfc and rfc != 'XAXX010101000':
        customer['rfc'] = rfc

    # Name pieces reused by PF/PM and fallback flows.
    first_name = safe_string(get_field(row, 'CLIE_NOMBRE'))
    paternal = safe_string(get_field(row, 'CLIE_APELLIDOPATERNO'))
    maternal = safe_string(get_field(row, 'CLIE_APELLIDOMATERNO'))
    razon_factura = safe_string(get_field(row, 'FAAU_RAZONFACTURA'))

    def add_pf_name_fields():
        name = {}
        if first_name:
            name['name'] = first_name
        if paternal:
            name['paternal'] = paternal
        if maternal:
            name['maternal'] = maternal
        if name:
            customer['name'] = name
            return True
        return False
    
    if person_type == 'PF':
        # Physical Customer
        add_pf_name_fields()
        
        curp = safe_string(get_field(row, 'CLIE_CURP'))
        if curp:
            customer['curp'] = curp
        
        economical_activity = safe_string(get_field(row, 'CVE_ACTI_ECON_PF'))
        if economical_activity and economical_activity != '0':
            customer['economical_activity'] = economical_activity
    
    elif person_type == 'PM':
        # Moral Customer
        denomination = (
            safe_string(get_field(row, 'CLIE_RAZONSOCIAL'))
            or razon_factura
            or first_name
        )
        if denomination:
            customer['denomination'] = denomination
        
        economical_activity = safe_string(get_field(row, 'CVE_ACTI_ECON_PM'))
        if economical_activity and economical_activity != '0':
            customer['economical_activity'] = economical_activity
        
        # Representatives
        rep_name = safe_string(get_field(row, 'CLIE_NOMBREREPLEGAL'))
        rep_paternal = safe_string(get_field(row, 'CLIE_APELLIDOPATERNOREPLEG'))
        rep_maternal = safe_string(get_field(row, 'CLIE_APELLIDOMATERNOREPLEG'))
        
        if rep_name or rep_paternal or rep_maternal:
            representative = {"id": f"{customer_id}-REP1"}
            
            rep_name_obj = {}
            if rep_name:
                rep_name_obj['name'] = rep_name
            if rep_paternal:
                rep_name_obj['paternal'] = rep_paternal
            if rep_maternal:
                rep_name_obj['maternal'] = rep_maternal
            
            if rep_name_obj:
                representative['name'] = rep_name_obj
            
            rep_birth_date = get_field(row, 'CLIE_FECHANACIMIENTOREPLEG')
            if rep_birth_date:
                representative['birth_date'] = parse_simple_date(rep_birth_date)
            
            rep_rfc = safe_string(get_field(row, 'CLIE_RFCREPLEGAL'))
            if rep_rfc:
                representative['rfc'] = rep_rfc
            
            rep_curp = safe_string(get_field(row, 'CLIE_CURPREPLEGAL'))
            if rep_curp:
                representative['curp'] = rep_curp
            
            customer['representatives'] = [representative]
    else:
        # Missing/unknown person type appears in export data.
        # Prefer PF-style name when available, otherwise fall back to denomination.
        has_pf_name = add_pf_name_fields()
        if not has_pf_name:
            denomination = safe_string(get_field(row, 'CLIE_RAZONSOCIAL')) or razon_factura
            if denomination:
                customer['denomination'] = denomination
        economical_activity = (
            safe_string(get_field(row, 'CVE_ACTI_ECON_PF'))
            or safe_string(get_field(row, 'CVE_ACTI_ECON_PM'))
        )
        if economical_activity and economical_activity != '0':
            customer['economical_activity'] = economical_activity
    
    return customer


def parse_order(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse order data from row"""
    invoice_no = safe_string(get_field(row, 'FAAU_NOFACTURA'))
    customer_id = safe_string(get_field(row, 'FAAU_CLIE_CLAVE'))
    vehicle_vin = safe_string(get_field(row, 'VEHI_SERIE'))
    
    if not invoice_no or not customer_id or not vehicle_vin:
        return None
    
    order_types = map_order_types_from_row(row)
    
    order = {
        "id": invoice_no,
        "customer_id": customer_id,
        "vehicle_id": vehicle_vin,
        "invoice_no": invoice_no,
        "organization": get_organization_from_row(row)
    }
    
    # Dates
    invoice_date_iso = parse_date(get_field(row, 'FAAU_FECHA'))
    if invoice_date_iso:
        order['invoice_date'] = invoice_date_iso
    
    mov_dt_iso = parse_date(get_field(row, 'FECHAMOV'))
    if mov_dt_iso:
        try:
            order['transaction_date'] = mov_dt_iso.split('T')[0]
        except Exception:
            pass
    elif invoice_date_iso:
        order['transaction_date'] = invoice_date_iso.split('T')[0]
    
    # Financial data
    iva = safe_float(get_field(row, 'FAAU_IVA'))
    isan = safe_float(get_field(row, 'FAAU_ISAN'))
    total = safe_float(get_field(row, 'FAAU_TOTAL'))
    subtotal = max(total - iva - isan, 0.0)
    
    order['subtotal'] = subtotal
    order['iva'] = iva
    order['isan'] = isan
    order['total'] = total
    
    # Seller
    seller_id = safe_string(get_field(row, 'FAAU_VEND_CLAVE'))
    if seller_id:
        order['seller_id'] = str(seller_id)
    
    # Transaction type and sub order type from mappings
    if order_types.get('transaction_type'):
        order['transaction_type'] = order_types['transaction_type']
    if order_types.get('sub_order_type'):
        order['sub_order_type'] = order_types['sub_order_type']
    
    # Status
    faau_status = safe_string(get_field(row, 'FAAU_STATUS'))
    if faau_status:
        order['status'] = get_order_status(faau_status)
    
    # Reference
    reference = safe_string(get_field(row, 'PRIM_FOLIO'))
    if reference:
        order['reference'] = str(reference)
    
    # Vendor RFC
    vendor_rfc = safe_string(get_field(row, 'CLAVE_SUJETO_OBLIGADO'))
    if vendor_rfc:
        order['vendor_rfc'] = vendor_rfc
    
    # Dealership
    dealership = safe_string(get_field(row, 'AGEN_AGENCIA'))
    if dealership:
        order['dealership'] = dealership
    
    # Metadata
    metadata = {}
    
    cfdi_uuid = safe_string(get_field(row, 'PRIM_UUIDS'))
    if cfdi_uuid:
        metadata['cfdi_uuid'] = cfdi_uuid
    
    form_tipoventa = safe_string(get_field(row, 'FAAU_FORM_TIPOVENTA'))
    if form_tipoventa:
        metadata['form_tipoventa'] = form_tipoventa
    
    form_descripcion = safe_string(get_field(row, 'FORM_DESCRIPCION'))
    if form_descripcion:
        metadata['form_descripcion'] = form_descripcion
    
    dms = safe_string(get_field(row, 'DMS'))
    if dms:
        metadata['dms'] = dms
    
    period = safe_string(get_field(row, 'PERIODO'))
    if period:
        metadata['period'] = period
    
    seller_name = safe_string(get_field(row, 'VEND_NOMBRE'))
    if seller_name:
        metadata['seller_name'] = seller_name
    
    branch = safe_string(get_field(row, 'AGEN_NOMBRE_SUCURSAL'))
    if branch:
        metadata['branch'] = branch
    
    if metadata:
        order['metadata'] = metadata
    
    # NOTE: For now, always set status to pending. Later we will use
    # get_order_status(faau_status) to map FAAU_STATUS to the appropriate value.
    order['status'] = 'pending'
    
    return order


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def build_dsn(db_config: dict) -> str:
    """Build Oracle DSN string with SOURCE_ROUTE through tunnel."""
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


def fetch_from_database(db_name: str, db_config: dict, user: str, password: str, 
                        from_date: Optional[str] = None, to_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all rows from a database and convert to dicts."""
    print(f"\n{'='*60}")
    print(f"Fetching from: {db_name} ({db_config['group']})")
    if from_date or to_date:
        print(f"Date filter: {from_date or 'any'} to {to_date or 'any'}")
    print("-" * 60)
    
    dsn = build_dsn(db_config)
    rows = []
    query = build_query(from_date, to_date)
    
    try:
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        cursor = conn.cursor()
        cursor.execute(query)
        
        # Get column names
        columns = [col[0] for col in cursor.description]
        
        # Convert rows to dicts
        for row in cursor:
            row_dict = dict(zip(columns, row))
            rows.append(row_dict)
        
        print(f"✓ Fetched {len(rows)} rows")
        
        cursor.close()
        conn.close()
        
    except oracledb.Error as e:
        print(f"✗ Database error: {e}")
    
    return rows


# =============================================================================
# API FUNCTIONS
# =============================================================================

def _collect_text_values(value: Any, parts: List[str]):
    """Recursively collect string values from API response payloads."""
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            parts.append(cleaned.lower())
        return
    
    if isinstance(value, dict):
        for nested in value.values():
            _collect_text_values(nested, parts)
        return
    
    if isinstance(value, list):
        for nested in value:
            _collect_text_values(nested, parts)


def _extract_response_text(response_data: Any) -> str:
    """Extract searchable text from a JSON/text API response."""
    parts: List[str] = []
    _collect_text_values(response_data, parts)
    return " ".join(parts)


def _detect_missing_order_dependencies(status: Optional[int], response_data: Any) -> Dict[str, bool]:
    """Detect if order failure points to missing customer and/or vehicle dependencies."""
    if status is None or (200 <= status < 300):
        return {"customer": False, "vehicle": False}
    
    text = _extract_response_text(response_data)
    if not text:
        return {"customer": False, "vehicle": False}
    
    missing_customer = (
        "customer not found" in text
        or ("customer processing failed" in text and "not found" in text)
    )
    missing_vehicle = (
        "vehicle not found" in text
        or ("vehicle processing failed" in text and "not found" in text)
    )
    return {"customer": missing_customer, "vehicle": missing_vehicle}


def _format_response_for_log(response_data: Any, max_chars: int = 400) -> str:
    """Compact API response payload for readable retry diagnostics."""
    text = str(response_data).replace("\n", " ")
    if len(text) > max_chars:
        return text[:max_chars] + "...<truncated>"
    return text


def _prepare_recovery_customer_payload(
    customer_payload: Dict[str, Any],
    order: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Prepare customer payload for dependency recovery retries.

    Recovery must target the same organization as the failing order, otherwise
    order resolution can still fail with "customer not found".
    """
    prepared_payload = dict(customer_payload)
    order_organization = safe_string(order.get("organization"))
    if not order_organization:
        return prepared_payload

    prepared_payload["organization"] = order_organization
    return prepared_payload


async def _post_item(session: aiohttp.ClientSession, endpoint: str, item: Dict[str, Any], verbose: bool = False) -> Dict[str, Any]:
    """POST a single payload and capture response details."""
    # Get fresh headers (token auto-refreshes if needed)
    headers = token_manager.get_headers()
    
    if verbose:
        import json
        print(f"  [{endpoint}] Payload:")
        print(json.dumps(item, indent=2, default=str))
    
    try:
        async with session.post(f"{API_BASE}/{endpoint}", headers=headers, json=item) as response:
            try:
                response_data = await response.json(content_type=None)
            except Exception:
                response_data = await response.text()
            return {
                "status": response.status,
                "response_data": response_data,
                "error": None,
            }
    except Exception as e:
        return {
            "status": None,
            "response_data": None,
            "error": str(e),
        }


async def _send_single_item(
    session: aiohttp.ClientSession,
    endpoint: str,
    item: Dict[str, Any],
    item_num: int,
    verbose: bool = False,
    force_send: bool = False,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Send one item with progress tracking and consistent logging."""
    item_id = item.get("id")
    progress_id = progress_entity_id(endpoint, item)
    item_label = label or f"Item {item_num}"

    if not force_send and backend_lookup_endpoint(endpoint) is not None:
        lookup = await _backend_item_exists(session, endpoint, item)
        if lookup["exists"] is True:
            print(f"  [{endpoint}] {item_label} (id={item_id}): SKIPPED (exists in backend)")
            return {
                "ok": True,
                "skipped": True,
                "status": lookup["status"],
                "response_data": lookup["response_data"],
                "item_id": item_id,
            }
        if lookup["exists"] is None:
            print(
                f"  [{endpoint}] {item_label} (id={item_id}): "
                f"GET check failed ({lookup['status']}) - {lookup['response_data']}"
            )
            return {
                "ok": False,
                "skipped": False,
                "status": lookup["status"],
                "response_data": lookup["response_data"],
                "item_id": item_id,
            }
    
    # Skip if already sent (from progress file), unless this is a forced recovery send
    if (
        not force_send
        and backend_lookup_endpoint(endpoint) is None
        and progress_tracker
        and progress_id
        and progress_tracker.is_sent(endpoint, progress_id)
    ):
        scoped_note = f", progress_id={progress_id}" if progress_id != item_id else ""
        print(f"  [{endpoint}] {item_label} (id={item_id}{scoped_note}): SKIPPED (already sent)")
        return {
            "ok": True,
            "skipped": True,
            "status": None,
            "response_data": None,
            "item_id": item_id,
        }
    
    post_result = await _post_item(session, endpoint, item, verbose=verbose)
    error = post_result.get("error")
    if error:
        print(f"  [{endpoint}] Error on {item_label} (id={item_id}): {error}")
        return {
            "ok": False,
            "skipped": False,
            "status": None,
            "response_data": None,
            "item_id": item_id,
        }
    
    status = post_result.get("status")
    response_data = post_result.get("response_data")
    print(f"  [{endpoint}] {item_label} (id={item_id}): {status} - {response_data}")
    
    ok = status is not None and 200 <= status < 300
    if ok and progress_tracker and progress_id:
        progress_tracker.mark_sent(endpoint, progress_id)
    
    return {
        "ok": ok,
        "skipped": False,
        "status": status,
        "response_data": response_data,
        "item_id": item_id,
    }


async def _recover_order_dependencies_and_retry(
    session: aiohttp.ClientSession,
    order: Dict[str, Any],
    item_num: int,
    missing_customer: bool,
    missing_vehicle: bool,
    customers_by_key: Dict[str, Dict[str, Any]],
    vehicles_by_id: Dict[str, Dict[str, Any]],
    verbose: bool = False,
) -> bool:
    """Re-send missing dependencies for an order and retry it."""
    order_id = order.get("id")
    customer_id = order.get("customer_id")
    vehicle_id = order.get("vehicle_id")
    
    print(
        f"  [orders] Item {item_num} (id={order_id}): dependency recovery "
        f"(customer_missing={missing_customer}, vehicle_missing={missing_vehicle})"
    )
    
    dependencies_ok = True
    
    if missing_customer:
        customer_key = order_customer_payload_key(order)
        customer_payload = customers_by_key.get(customer_key)
        if customer_payload:
            recovery_customer_payload = _prepare_recovery_customer_payload(customer_payload, order)
            original_organization = safe_string(customer_payload.get("organization"))
            recovery_organization = safe_string(recovery_customer_payload.get("organization"))
            if original_organization != recovery_organization:
                print(
                    f"  [orders] Item {item_num} (id={order_id}): "
                    f"recovery customer organization override "
                    f"({original_organization} -> {recovery_organization})"
                )
            customer_result = await _send_single_item(
                session=session,
                endpoint="customers",
                item=recovery_customer_payload,
                item_num=item_num,
                verbose=verbose,
                force_send=True,
                label=f"Recovery customer for order {order_id}",
            )
            if not customer_result["ok"]:
                dependencies_ok = False
        else:
            print(
                f"  [orders] Recovery skipped: customer payload not found for "
                f"order id={order_id}, customer_id={customer_id}, "
                f"organization={order.get('organization')}"
            )
            dependencies_ok = False
    
    if missing_vehicle:
        vehicle_payload = vehicles_by_id.get(vehicle_id)
        if vehicle_payload:
            vehicle_result = await _send_single_item(
                session=session,
                endpoint="vehicles",
                item=vehicle_payload,
                item_num=item_num,
                verbose=verbose,
                force_send=True,
                label=f"Recovery vehicle for order {order_id}",
            )
            if not vehicle_result["ok"]:
                dependencies_ok = False
        else:
            print(
                f"  [orders] Recovery skipped: vehicle payload not found for "
                f"order id={order_id}, vehicle_id={vehicle_id}"
            )
            dependencies_ok = False
    
    if not dependencies_ok:
        print(f"  [orders] Item {item_num} (id={order_id}): dependency recovery failed")
        return False
    
    total_attempts = len(ORDER_RECOVERY_RETRY_DELAYS)
    last_retry_result: Optional[Dict[str, Any]] = None

    for attempt, delay_seconds in enumerate(ORDER_RECOVERY_RETRY_DELAYS, start=1):
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        retry_result = await _send_single_item(
            session=session,
            endpoint="orders",
            item=order,
            item_num=item_num,
            verbose=verbose,
            force_send=True,
            label=f"Retry order after dependency recovery ({attempt}/{total_attempts})",
        )
        last_retry_result = retry_result

        if retry_result["ok"]:
            print(
                f"  [orders] Item {item_num} (id={order_id}): "
                f"RECOVERED on retry attempt {attempt}/{total_attempts}"
            )
            return True

    if last_retry_result:
        status = last_retry_result.get("status")
        response_data = _format_response_for_log(last_retry_result.get("response_data"))
        print(
            f"  [orders] Item {item_num} (id={order_id}): "
            f"retry failed after dependency recovery "
            f"(status={status}, response={response_data})"
        )
    else:
        print(f"  [orders] Item {item_num} (id={order_id}): retry failed after dependency recovery")
    return False


async def send_batch(
    session: aiohttp.ClientSession,
    endpoint: str,
    batch: List[Dict],
    batch_num: int,
    total_batches: int,
    verbose: bool = False,
    customers_by_key: Optional[Dict[str, Dict[str, Any]]] = None,
    vehicles_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
):
    """Send a batch of items to an endpoint."""
    print(f"Sending batch {batch_num}/{total_batches} to {endpoint} ({len(batch)} items)...")
    
    stats = {"sent": 0, "skipped": 0, "errors": 0, "recovered": 0}
    
    for idx, item in enumerate(batch, start=1):
        send_result = await _send_single_item(
            session=session,
            endpoint=endpoint,
            item=item,
            item_num=idx,
            verbose=verbose,
        )
        
        if send_result["skipped"]:
            stats["skipped"] += 1
            continue
        
        if send_result["ok"]:
            stats["sent"] += 1
            continue
        
        recovered = False
        if endpoint == "orders" and customers_by_key is not None and vehicles_by_id is not None:
            dependency_state = _detect_missing_order_dependencies(
                status=send_result.get("status"),
                response_data=send_result.get("response_data"),
            )
            if dependency_state["customer"] or dependency_state["vehicle"]:
                recovered = await _recover_order_dependencies_and_retry(
                    session=session,
                    order=item,
                    item_num=idx,
                    missing_customer=dependency_state["customer"],
                    missing_vehicle=dependency_state["vehicle"],
                    customers_by_key=customers_by_key,
                    vehicles_by_id=vehicles_by_id,
                    verbose=verbose,
                )
        
        if recovered:
            stats["sent"] += 1
            stats["recovered"] += 1
        else:
            stats["errors"] += 1
    
    return stats


async def send_to_api(vehicles: List[Dict], customers: List[Dict], orders: List[Dict], 
                      batch_size: int = 5, verbose: bool = False, continue_from: Optional[str] = None,
                      db_name: Optional[str] = None):
    """Send all entities to API"""
    global progress_tracker
    
    # Initialize progress tracker for this DB
    if db_name:
        progress_tracker = ProgressTracker(db_name)
    
    # Initialize token (will auto-refresh every 45 min)
    token_manager.get_token()
    
    # Parse continue_from (format: "vehicles-ID", "customers-ID", or "orders-ID")
    skip_vehicles = False
    skip_customers = False
    skip_until_id = None
    skip_entity_type = None
    
    if continue_from:
        parts = continue_from.split("-", 1)
        if len(parts) == 2:
            skip_entity_type, skip_until_id = parts[0], parts[1]
            if skip_entity_type == "customers":
                skip_vehicles = True
            elif skip_entity_type == "orders":
                skip_vehicles = True
                skip_customers = True
            print(f"Continuing from {skip_entity_type} ID: {skip_until_id}")
    
    overall_stats = {
        "vehicles": {"sent": 0, "skipped": 0, "errors": 0, "recovered": 0},
        "customers": {"sent": 0, "skipped": 0, "errors": 0, "recovered": 0},
        "orders": {"sent": 0, "skipped": 0, "errors": 0, "recovered": 0},
    }
    
    customers_by_key = {customer_payload_key(c): c for c in customers if customer_payload_key(c)}
    vehicles_by_id = {v["id"]: v for v in vehicles if v.get("id")}
    
    async with aiohttp.ClientSession() as session:
        # Send vehicles
        if not skip_vehicles:
            print("\n=== SENDING VEHICLES ===")
            found_skip_id = skip_entity_type != "vehicles"
            for i in range(0, len(vehicles), batch_size):
                batch = vehicles[i:i+batch_size]
                
                # If we're looking for a specific ID to continue from
                if not found_skip_id:
                    new_batch = []
                    for item in batch:
                        if found_skip_id:
                            new_batch.append(item)
                        elif item.get('id') == skip_until_id:
                            found_skip_id = True
                    batch = new_batch
                    if not batch:
                        continue
                
                batch_num = (i // batch_size) + 1
                total_batches = (len(vehicles) + batch_size - 1) // batch_size
                batch_stats = await send_batch(
                    session=session,
                    endpoint="vehicles",
                    batch=batch,
                    batch_num=batch_num,
                    total_batches=total_batches,
                    verbose=verbose,
                )
                for key, value in batch_stats.items():
                    overall_stats["vehicles"][key] += value
        else:
            print("\n=== SKIPPING VEHICLES (continue-from) ===")
        
        # Send customers
        if not skip_customers:
            print("\n=== SENDING CUSTOMERS ===")
            found_skip_id = skip_entity_type != "customers"
            for i in range(0, len(customers), batch_size):
                batch = customers[i:i+batch_size]
                
                if not found_skip_id:
                    new_batch = []
                    for item in batch:
                        if found_skip_id:
                            new_batch.append(item)
                        elif item.get('id') == skip_until_id:
                            found_skip_id = True
                    batch = new_batch
                    if not batch:
                        continue
                
                batch_num = (i // batch_size) + 1
                total_batches = (len(customers) + batch_size - 1) // batch_size
                batch_stats = await send_batch(
                    session=session,
                    endpoint="customers",
                    batch=batch,
                    batch_num=batch_num,
                    total_batches=total_batches,
                    verbose=verbose,
                )
                for key, value in batch_stats.items():
                    overall_stats["customers"][key] += value
        else:
            print("\n=== SKIPPING CUSTOMERS (continue-from) ===")
        
        # Send orders
        print("\n=== SENDING ORDERS ===")
        found_skip_id = skip_entity_type != "orders"
        for i in range(0, len(orders), batch_size):
            batch = orders[i:i+batch_size]
            
            if not found_skip_id:
                new_batch = []
                for item in batch:
                    if found_skip_id:
                        new_batch.append(item)
                    elif item.get('id') == skip_until_id:
                        found_skip_id = True
                batch = new_batch
                if not batch:
                    continue
            
            batch_num = (i // batch_size) + 1
            total_batches = (len(orders) + batch_size - 1) // batch_size
            batch_stats = await send_batch(
                session=session,
                endpoint="orders",
                batch=batch,
                batch_num=batch_num,
                total_batches=total_batches,
                verbose=verbose,
                customers_by_key=customers_by_key,
                vehicles_by_id=vehicles_by_id,
            )
            for key, value in batch_stats.items():
                overall_stats["orders"][key] += value
            await asyncio.sleep(0.25)
    
    print("\n=== SEND SUMMARY ===")
    for endpoint in ("vehicles", "customers", "orders"):
        stats = overall_stats[endpoint]
        print(
            f"  {endpoint}: sent={stats['sent']}, skipped={stats['skipped']}, "
            f"errors={stats['errors']}"
        )
    print(f"  orders recovered after dependency resend: {overall_stats['orders']['recovered']}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Fetch GMUni data from Oracle and send to API")
    parser.add_argument("--password", type=str, required=True, help="Oracle password")
    parser.add_argument("--user", type=str, default="PRESA", help="Oracle username")
    parser.add_argument("--db", type=str, help="Specific database to query (default: all)")
    parser.add_argument("--batch-size", type=int, default=5, help="API batch size")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't send to API")
    parser.add_argument("--list", action="store_true", help="List available databases")
    parser.add_argument("--from-date", type=str, help="Filter: invoices from this date (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=str, help="Filter: invoices up to this date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, help="Limit: only send first N orders (and their vehicles/customers)")
    parser.add_argument("--verbose", action="store_true", help="Print payloads before sending")
    parser.add_argument("--continue-from", type=str, help="Continue from: vehicles-ID, customers-ID, or orders-ID")
    args = parser.parse_args()
    
    if args.list:
        print("Available databases:")
        for name, config in DATABASES.items():
            print(f"  {name} ({config['group']})")
        return
    
    print(f"\nUsing connection-manager tunnel at {LOCAL_TUNNEL_HOST}:{LOCAL_TUNNEL_PORT}")
    print("Make sure SSH tunnel is running:")
    print("  ssh -o PubkeyAuthentication=no -N \\")
    print("    -L 16223:192.168.10.88:6223 \\")
    print("    -L 16224:192.168.11.160:1521 \\")
    print("    -L 16225:192.168.11.173:1521 \\")
    print("    -L 16226:192.168.10.85:1521 \\")
    print("    PRESA@192.168.10.83")
    
    # Determine which databases to query
    if args.db:
        if args.db not in DATABASES:
            print(f"Error: Unknown database '{args.db}'")
            print("Use --list to see available databases")
            sys.exit(1)
        dbs_to_query = {args.db: DATABASES[args.db]}
    else:
        dbs_to_query = DATABASES
    
    # Collect all rows from all databases
    all_rows = []
    for db_name, db_config in dbs_to_query.items():
        rows = fetch_from_database(db_name, db_config, args.user, args.password,
                                   args.from_date, args.to_date)
        all_rows.extend(rows)
    
    print(f"\n{'='*60}")
    print(f"TOTAL ROWS FETCHED: {len(all_rows)}")
    print("=" * 60)
    
    # Parse entities. GMUNI customer ids can be recycled across sub-orgs, so
    # customers are deduplicated by id+organization, not by id alone.
    vehicles_map: Dict[str, Dict[str, Any]] = {}
    customers_map: Dict[str, Dict[str, Any]] = {}
    orders_map: Dict[str, Dict[str, Any]] = {}
    
    for row in all_rows:
        vehicle = parse_vehicle(row)
        customer = parse_customer(row)
        order = parse_order(row)
        
        if vehicle and vehicle.get('id'):
            vehicles_map[vehicle['id']] = vehicle
        if customer and customer.get('id'):
            scoped_key = customer_payload_key(customer)
            if scoped_key:
                customers_map[scoped_key] = customer
        if order and order.get('id'):
            orders_map[order['id']] = order
    
    vehicles = list(vehicles_map.values())
    customers = list(customers_map.values())
    orders = list(orders_map.values())
    
    print(f"\nParsed (deduplicated):")
    print(f"  Vehicles: {len(vehicles)}")
    print(f"  Customers: {len(customers)}")
    print(f"  Orders: {len(orders)}")
    
    # Apply limit if specified
    if args.limit:
        # Limit orders and only include their associated vehicles/customers
        orders = orders[:args.limit]
        order_vehicle_ids = {o['vehicle_id'] for o in orders}
        order_customer_keys = {order_customer_payload_key(o) for o in orders}
        vehicles = [v for v in vehicles if v['id'] in order_vehicle_ids]
        customers = [c for c in customers if customer_payload_key(c) in order_customer_keys]
        print(f"\nAfter --limit {args.limit}:")
        print(f"  Vehicles: {len(vehicles)}")
        print(f"  Customers: {len(customers)}")
        print(f"  Orders: {len(orders)}")
    
    if args.dry_run:
        print("\n[DRY RUN] Skipping API calls")
        # Print sample data
        if vehicles:
            print("\nSample vehicle:")
            import json
            print(json.dumps(vehicles[0], indent=2, default=str))
        if orders:
            print("\nSample order:")
            print(json.dumps(orders[0], indent=2, default=str))
    else:
        # Get DB name for progress tracking
        db_name = args.db if args.db else "all_dbs"
        asyncio.run(send_to_api(vehicles, customers, orders, args.batch_size, args.verbose, args.continue_from, db_name))
    
    print("\n=== COMPLETE ===")


if __name__ == "__main__":
    main()
