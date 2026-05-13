"""
GMUni Data Mappings Module

This module handles the transformation of GMUni source data to the backend API format.
Currently uses in-memory dictionaries, but designed to be easily swapped for SQL lookups.
"""

from typing import Optional, Dict, Any


# =============================================================================
# TRANSACTION TYPE MAPPING
# Based on FORM_CARTERA -> TransactionType enum
# =============================================================================

CARTERA_TO_TRANSACTION_TYPE: Dict[str, str] = {
    # Retail (new vehicles)
    "AUTO": "retail",
    "FLOT": "retail",
    "GMAC": "retail",
    "PONE": "retail",
    
    # Pre-owned (seminuevos)
    "USAD": "pre_owned",
    
    # Exchange (intercambios)
    "DIST": "exchange",
    "SUC": "exchange",
    
    # Administrative/Service - default to retail
    "SERV": "retail",
    "REFA": "retail",
    "HYP": "retail",
    "ADM": "retail",
    "SUCR": "retail",
    "SUCS": "retail",
    "SUCA": "retail",
}


def get_transaction_type(cartera: Optional[str]) -> Optional[str]:
    """
    Map FORM_CARTERA to TransactionType enum value.
    
    Args:
        cartera: The FORM_CARTERA value (e.g., "AUTO", "USAD", "DIST")
    
    Returns:
        TransactionType string ("retail", "pre_owned", "exchange") or None
    """
    if not cartera:
        return None
    
    cartera_upper = cartera.strip().upper()
    return CARTERA_TO_TRANSACTION_TYPE.get(cartera_upper, "retail")


# =============================================================================
# SUB ORDER TYPE MAPPING
# Based on FORM_GRUPODEVENTADIR -> SubOrderType enum
# =============================================================================

GRUPO_VENTA_TO_SUB_ORDER_TYPE: Dict[str, str] = {
    # Fleet
    "FLOTILLAS": "fleet",
    
    # Bank (financiera)
    "FINANCIERA": "bank",
    "FINANCIERA PLANTA": "bank",
    "PLAN ONE": "bank",
    
    # Out right (contado/tradicional)
    "TRADICIONAL": "out_right",
    
    # Exchange
    "INTERCAMBIOS": "exchange",
    
    # Seminuevos - map based on payment type
    "SEMINUEVOS": "out_right",
    "SEMINUEVOS INTERCAMBIOS": "exchange",
    
    # Sucursales
    "SUCURSALES": "exchange",
    
    # Demos
    "DEMOS": "out_right",
}


def get_sub_order_type(grupo_venta_dir: Optional[str]) -> Optional[str]:
    """
    Map FORM_GRUPODEVENTADIR to SubOrderType enum value.
    
    Args:
        grupo_venta_dir: The FORM_GRUPODEVENTADIR value (e.g., "TRADICIONAL", "FINANCIERA")
    
    Returns:
        SubOrderType string ("fleet", "bank", "out_right", "exchange", etc.) or None
    """
    if not grupo_venta_dir:
        return None
    
    grupo_upper = grupo_venta_dir.strip().upper()
    return GRUPO_VENTA_TO_SUB_ORDER_TYPE.get(grupo_upper)


# =============================================================================
# FORM TIPOVENTA LOOKUP
# Maps FAAU_FORM_TIPOVENTA to cartera and grupo for secondary lookups
# This would be replaced with SQL: SELECT * FROM form_ventas WHERE FORM_TIPOVENTA = ?
# =============================================================================

FORM_TIPOVENTA_MAP: Dict[str, Dict[str, str]] = {
    # Pasajeros (AN-)
    "AN-HSBC": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-INTER": {"cartera": "DIST", "grupo": "INTERCAMBIOS"},
    "AN-BNP PAR": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-PLANONE": {"cartera": "PONE", "grupo": "PLAN ONE"},
    "AN-SANTAND": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-SCOTIA": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-TRADICI": {"cartera": "AUTO", "grupo": "TRADICIONAL"},
    "AN-FINANCI": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-DATAMOV": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-CETELEM": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-BNREGIO": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-AFIRME": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-BANCOME": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-BANORTE": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "AN-FLOTILL": {"cartera": "FLOT", "grupo": "FLOTILLAS"},
    "AN-GMF": {"cartera": "GMAC", "grupo": "FINANCIERA PLANTA"},
    "AN-SUAUTO": {"cartera": "AUTO", "grupo": "FINANCIERA PLANTA"},
    "AN-SCURSAL": {"cartera": "SUC", "grupo": "SUCURSALES"},
    "AN-AUTOFIN": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    
    # Comerciales (CO-)
    "CO-TRADICI": {"cartera": "AUTO", "grupo": "TRADICIONAL"},
    "CO-HSBC": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-INTER": {"cartera": "DIST", "grupo": "INTERCAMBIOS"},
    "CO-BNP PAR": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-PLANONE": {"cartera": "PONE", "grupo": "PLAN ONE"},
    "CO-SANTAND": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-SCOTIA": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-FINANCI": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-DATAMOV": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-CETELEM": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-BNREGIO": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-AFIRME": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-BANCOME": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-BANORTE": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    "CO-FLOTILL": {"cartera": "FLOT", "grupo": "FLOTILLAS"},
    "CO-GMF": {"cartera": "GMAC", "grupo": "FINANCIERA PLANTA"},
    "CO-SUAUTO": {"cartera": "AUTO", "grupo": "FINANCIERA PLANTA"},
    "CO-SCURSAL": {"cartera": "SUC", "grupo": "SUCURSALES"},
    "CO-AUTOFIN": {"cartera": "AUTO", "grupo": "FINANCIERA"},
    
    # Seminuevos (AS-)
    "AS-TRADICI": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-BANCOME": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-BNREGIO": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-BANORTE": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-BNP PAR": {"cartera": "AUTO", "grupo": "SEMINUEVOS"},
    "AS-FINANCI": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-GMF": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-HSBC": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-PLANONE": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-SANTAND": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-SCOTIA": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-DATAMOV": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-CETELEM": {"cartera": "USAD", "grupo": "SEMINUEVOS"},
    "AS-AFIRME": {"cartera": "USAD", "grupo": "FINANCIERA"},
    "AS-INTER": {"cartera": "SUC", "grupo": "SEMINUEVOS INTERCAMBIOS"},
    "AS-INTERFV": {"cartera": "SUC", "grupo": "SEMINUEVOS INTERCAMBIOS"},
    "AS-SCURSAL": {"cartera": "SUCA", "grupo": "SUCURSALES"},
    
    # Demo
    "DEMO": {"cartera": "AUTO", "grupo": "DEMOS"},
}

# Normalization aliases found in real data exports.
FORM_TIPOVENTA_ALIASES: Dict[str, str] = {
    "AN-BNP": "AN-BNP PAR",
    "CO-BNP": "CO-BNP PAR",
    "AN-INTERCA": "AN-INTER",
    "CO-INTERCA": "CO-INTER",
    "AN-SCOTIAB": "AN-SCOTIA",
    "CO-SCOTIAB": "CO-SCOTIA",
    "AN-DATMVL": "AN-DATAMOV",
}


def lookup_form_tipoventa(tipo_venta: Optional[str]) -> Dict[str, Optional[str]]:
    """
    Look up FORM_TIPOVENTA to get cartera and grupo values.
    
    Args:
        tipo_venta: The FAAU_FORM_TIPOVENTA value (e.g., "CO-TRADICI")
    
    Returns:
        Dict with 'cartera' and 'grupo' keys
    """
    if not tipo_venta:
        return {"cartera": None, "grupo": None}
    
    tipo_upper = tipo_venta.strip().upper()
    normalized_tipo = FORM_TIPOVENTA_ALIASES.get(tipo_upper, tipo_upper)
    result = FORM_TIPOVENTA_MAP.get(normalized_tipo, {})
    
    return {
        "cartera": result.get("cartera"),
        "grupo": result.get("grupo")
    }


def infer_cartera_from_context(
    tipo_venta: Optional[str],
    grupo_venta_dir: Optional[str],
    tipo_aviso: Optional[str],
) -> Optional[str]:
    """
    Infer FORM_CARTERA when FAAU_FORM_TIPOVENTA doesn't have an explicit mapping.

    This keeps unknown tipoventa variants from dropping `transaction_type` in payloads.
    """
    tipo = (tipo_venta or "").strip().upper()
    grupo = (grupo_venta_dir or "").strip().upper()
    aviso = (tipo_aviso or "").strip().upper()

    if not tipo and not grupo and not aviso:
        return None

    # Intercambios have priority even when code prefix looks like seminuevos.
    if (
        "INTER" in tipo
        or "INTERCAMBI" in grupo
        or "NUEVO INTER" in aviso
        or "SEMINUEVO INTER" in aviso
    ):
        return "DIST"

    # Seminuevos / usados.
    if "SEMINUEVO" in aviso or "SEMINUEVOS" in grupo:
        return "USAD"
    if tipo.startswith(("US", "UA", "UC")):
        return "USAD"

    # Common retail-only labels used by several brands.
    if tipo in {"CONTADO", "EFECTIVO", "PLAN ONE"}:
        return "AUTO"

    retail_tokens = (
        "MENUDEO",
        "FINAN",
        "BAN",
        "BNP",
        "SCOT",
        "HSBC",
        "SANT",
        "CETE",
        "AFIRME",
        "AUTOFIN",
        "KUNA",
        "CRFACT",
        "NEXU",
        "MSTAR",
        "GMF",
        "VACH",
        "CONTADO",
        "PLAN",
    )
    if tipo and (
        tipo.startswith(("AN-", "CO-", "K", "P-", "C-", "F-", "M-", "SA-", "SL-", "SO-"))
        or any(token in tipo for token in retail_tokens)
    ):
        return "AUTO"

    return None


# =============================================================================
# ORDER STATUS MAPPING
# Based on FAAU_STATUS -> OrderStatus enum
# =============================================================================

STATUS_MAP: Dict[str, str] = {
    "AC": "pending",      # Active
    "CA": "cancelled",    # Cancelled
    "PA": "fulfilled",    # Paid/Fulfilled
    "CO": "fulfilled",    # Completed
}


def get_order_status(faau_status: Optional[str]) -> str:
    """
    Map FAAU_STATUS to OrderStatus enum value.
    
    Args:
        faau_status: The FAAU_STATUS value (e.g., "AC", "CA")
    
    Returns:
        OrderStatus string ("pending", "fulfilled", "cancelled")
    """
    if not faau_status:
        return "pending"
    
    status_upper = faau_status.strip().upper()
    return STATUS_MAP.get(status_upper, "pending")


# =============================================================================
# ORGANIZATION ID GENERATION
# Format: EMPR_NOMBRE#EMPR_EMPRESAID#AGEN_IDAGENCIA
# =============================================================================

def build_organization_id(
    empr_nombre: Optional[str],
    empr_empresaid: Optional[str],
    agen_idagencia: Optional[str]
) -> str:
    """
    Build the organization ID from component parts.
    
    Format: EMPR_NOMBRE--EMPR_EMPRESAID--AGEN_IDAGENCIA
    Example: "CAR ONE AMERICANA--3--1"
    
    Args:
        empr_nombre: Company name (e.g., "CAR ONE AMERICANA")
        empr_empresaid: Company ID (e.g., "3")
        agen_idagencia: Agency ID (e.g., "1")
    
    Returns:
        Formatted organization string
    """
    parts = [
        (empr_nombre or "").strip().rstrip(','),
        (empr_empresaid or "").strip(),
        (agen_idagencia or "").strip()
    ]
    return "--".join(parts)


# =============================================================================
# COMPLETE ORDER MAPPING
# High-level function to map all order fields from source row
# =============================================================================

def map_order_types_from_row(row: Dict[str, str]) -> Dict[str, Optional[str]]:
    """
    Extract and map transaction_type and sub_order_type from a data row.
    
    Tries multiple strategies:
    1. Direct lookup via FAAU_FORM_TIPOVENTA
    2. Fallback to FORM_CARTERA if available
    3. Fallback to FORM_GRUPODEVENTADIR if available
    
    Args:
        row: Dictionary containing the source data row
    
    Returns:
        Dict with 'transaction_type' and 'sub_order_type' keys
    """
    # Strategy 1: Use FAAU_FORM_TIPOVENTA for lookup
    tipo_venta = row.get('FAAU_FORM_TIPOVENTA') or row.get('EXP_FAAU_FORM_TIPOVENTA')
    form_data = lookup_form_tipoventa(tipo_venta)
    
    # Get cartera - prefer lookup result, then direct field, then context inference
    cartera = form_data.get("cartera")
    if not cartera:
        cartera = row.get('FORM_CARTERA') or row.get('EXP_FORM_CARTERA')
    
    # Get grupo - prefer lookup result, fallback to direct field
    grupo = form_data.get("grupo")
    if not grupo:
        grupo = row.get('FORM_GRUPODEVENTADIR') or row.get('EXP_FORM_GRUPODEVENTADIR')

    if not cartera:
        tipo_aviso = row.get('TIPO_AVISO') or row.get('EXP_TIPO_AVISO')
        cartera = infer_cartera_from_context(
            tipo_venta=tipo_venta,
            grupo_venta_dir=grupo,
            tipo_aviso=tipo_aviso,
        )
    
    return {
        "transaction_type": get_transaction_type(cartera),
        "sub_order_type": get_sub_order_type(grupo)
    }


def get_organization_from_row(row: Dict[str, str]) -> str:
    """
    Extract organization ID from a data row.
    
    Args:
        row: Dictionary containing the source data row
    
    Returns:
        Organization ID string
    """
    empr_nombre = row.get('EMPR_NOMBRE') or row.get('EXP_EMPR_NOMBRE') or ''
    empr_empresaid = row.get('EMPR_EMPRESAID') or row.get('EXP_EMPR_EMPRESAID') or ''
    agen_idagencia = row.get('AGEN_IDAGENCIA') or row.get('EXP_AGEN_IDAGENCIA') or ''
    
    return build_organization_id(empr_nombre, str(empr_empresaid), str(agen_idagencia))
