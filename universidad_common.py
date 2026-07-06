#!/usr/bin/env python3
"""Shared helpers for the Universidad flattened sales/payments feed."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import aiohttp


API_BASE_DEFAULT = "https://api.presa.anjer.mx"
TOKEN_REFRESH_SECONDS = 45 * 60
BATCH_DELAY_SECONDS = 0.25
SAME_ORDER_PAYMENT_DELAY_SECONDS = 2.0

XLSX_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

GENERIC_RFCS = {"XAXX010101000", "XEXX010101000"}
VIN_YEAR_CODES = {
    "A": [1980, 2010],
    "B": [1981, 2011],
    "C": [1982, 2012],
    "D": [1983, 2013],
    "E": [1984, 2014],
    "F": [1985, 2015],
    "G": [1986, 2016],
    "H": [1987, 2017],
    "J": [1988, 2018],
    "K": [1989, 2019],
    "L": [1990, 2020],
    "M": [1991, 2021],
    "N": [1992, 2022],
    "P": [1993, 2023],
    "R": [1994, 2024],
    "S": [1995, 2025],
    "T": [1996, 2026],
    "V": [1997, 2027],
    "W": [1998, 2028],
    "X": [1999, 2029],
    "Y": [2000, 2030],
    "1": [2001],
    "2": [2002],
    "3": [2003],
    "4": [2004],
    "5": [2005],
    "6": [2006],
    "7": [2007],
    "8": [2008],
    "9": [2009],
}

SQL_REFERENCE_RE = re.compile(
    r"^(?:\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\.(?:\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)){0,2}$"
)
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    if not text or text.upper() == "NULL":
        return None
    return text


def safe_float(value: Any) -> Optional[float]:
    text = clean(value)
    if text is None:
        return None
    try:
        return float(text.replace(",", "").replace('"', ""))
    except Exception:
        return None


def safe_money(value: Any) -> Optional[float]:
    parsed = safe_float(value)
    if parsed is None:
        return None
    return round(parsed, 2)


def slug(value: Any, default: str = "unknown") -> str:
    text = clean(value) or default
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    compact = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-")
    return compact.upper() or default.upper()


def compact_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def is_cancelled_row(row: Dict[str, Any]) -> bool:
    return bool(clean(row.get("Cancelacion")) or clean(row.get("fechacanc")))


def parse_excel_serial(value: Any) -> Optional[datetime]:
    parsed = safe_float(value)
    if parsed is None or parsed < 20000:
        return None
    return datetime(1899, 12, 30) + timedelta(days=parsed)


DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%d/%m/%y %H:%M:%S",
    "%d/%m/%y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y",
    "%d-%m-%y %H:%M:%S",
    "%d-%m-%y",
)


def parse_datetime_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat() + "Z"

    excel_dt = parse_excel_serial(value)
    if excel_dt is not None:
        return excel_dt.isoformat() + "Z"

    text = clean(value)
    if text is None:
        return None

    normalized = text.rstrip("Z")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).isoformat() + "Z"
        except ValueError:
            continue
    return None


def parse_date_ymd(value: Any) -> Optional[str]:
    parsed = parse_datetime_iso(value)
    if not parsed:
        return None
    return parsed.split("T", 1)[0]


def normalize_sat_code(value: Any, default: str = "99") -> str:
    text = clean(value)
    if text is None:
        return default
    digits = re.sub(r"\D", "", text)
    if not digits:
        return default
    if len(digits) == 1:
        return digits.zfill(2)
    return digits[:2]


def organization_from_row(
    row: Dict[str, Any],
    override: Optional[str] = None,
    mode: str = "sucursal-cpny",
) -> str:
    if override:
        return override
    sucursal = clean(row.get("SUCURSAL")) or "UNIVERSIDAD"
    if mode == "sucursal":
        return sucursal
    cpny_id = clean(row.get("CpnyID"))
    if cpny_id:
        return f"{sucursal}--{cpny_id}"
    return sucursal


def customer_id_from_row(row: Dict[str, Any]) -> Optional[str]:
    rfc = clean(row.get("Rfc"))
    if rfc and rfc.upper() not in GENERIC_RFCS:
        return rfc.upper()

    name_slug = slug(row.get("Cliente") or row.get("Nombre") or row.get("Factura"), "CUSTOMER")
    if rfc:
        return compact_id(f"{rfc.upper()}-{name_slug}")
    if name_slug:
        return compact_id(f"CUSTOMER-{name_slug}")
    return None


def build_address(row: Dict[str, Any]) -> Dict[str, Any]:
    address: Dict[str, Any] = {}
    mapping = {
        "street": "Direcc",
        "neighborhood": "Direcc2",
        "city": "Ciudad",
        "state": "Estado",
        "postal_code": "CP",
        "country": "Pais",
    }
    for target, source in mapping.items():
        value = clean(row.get(source))
        if value:
            address[target] = value
    address.setdefault("country", "MX")
    return address


def build_phone(row: Dict[str, Any]) -> Optional[Dict[str, str]]:
    number = clean(row.get("Tel1")) or clean(row.get("Tel2"))
    if not number:
        return None
    return {"country_code": "52", "number": number}


def is_moral_customer(row: Dict[str, Any]) -> bool:
    customer_type = (clean(row.get("Tipo Cliente")) or "").upper()
    return "MORAL" in customer_type or "DISTRIB" in customer_type


def parse_customer(row: Dict[str, Any], organization: str) -> Optional[Dict[str, Any]]:
    customer_id = customer_id_from_row(row)
    if not customer_id:
        return None

    email = clean(row.get("EMailAddr"))
    phone = build_phone(row)
    address = build_address(row)
    rfc = clean(row.get("Rfc"))

    base: Dict[str, Any] = {
        "id": customer_id,
        "organization": organization,
        "metadata": {
            "source": "VENTAS UNIVERSIDAD",
            "cpny_id": clean(row.get("CpnyID")),
            "sucursal": clean(row.get("SUCURSAL")),
            "customer_type": clean(row.get("Tipo Cliente")),
        },
    }
    if email:
        base["email"] = email
    if phone:
        base["phone"] = phone
    if address:
        base["address"] = address
    if rfc and rfc.upper() not in GENERIC_RFCS:
        base["rfc"] = rfc.upper()

    if is_moral_customer(row):
        denomination = clean(row.get("Cliente")) or clean(row.get("Nombre"))
        if not denomination:
            return None
        base["denomination"] = denomination
        return base

    first_name = clean(row.get("Nombre")) or clean(row.get("Cliente")) or "SIN NOMBRE"
    name = {"name": first_name}
    paternal = clean(row.get("Paterno"))
    maternal = clean(row.get("Materno"))
    if paternal:
        name["paternal"] = paternal
    if maternal:
        name["maternal"] = maternal
    base["name"] = name

    curp = clean(row.get("curp"))
    if curp:
        base["curp"] = curp
    return base


def parse_vehicle(row: Dict[str, Any], organization: str) -> Optional[Dict[str, Any]]:
    vin = clean(row.get("NoSerie"))
    brand = clean(row.get("Marca"))
    model = clean(row.get("Linea")) or clean(row.get("Catalogo"))
    year = clean(row.get("Modelo")) or infer_year_from_vin(vin)
    if not vin or not brand or not model or not year:
        return None

    vehicle: Dict[str, Any] = {
        "id": vin,
        "brand": brand,
        "model": model,
        "vin": vin,
        "year": year,
        "organization": organization,
    }
    optional_fields = {
        "line": "Linea",
        "catalog_id": "Catalogo",
        "color": "Colorext",
        "interior_color": "Colorint",
        "doors": "Puertas",
        "cylinders": "Cilindros",
    }
    for target, source in optional_fields.items():
        value = clean(row.get(source))
        if value:
            vehicle[target] = value
    return vehicle


def infer_year_from_vin(vin: Optional[str]) -> Optional[str]:
    if not vin or len(vin) < 10:
        return None
    code = vin[9].upper()
    candidates = VIN_YEAR_CODES.get(code)
    if not candidates:
        return None
    upper_bound = datetime.now().year + 1
    valid = [year for year in candidates if year <= upper_bound]
    return str(max(valid or candidates))


def map_transaction_type(row: Dict[str, Any]) -> str:
    tipo = (clean(row.get("TipoVta")) or "").upper()
    marca = (clean(row.get("Marca")) or "").upper()
    if "INTER" in tipo:
        return "exchange"
    if "USAD" in tipo or marca == "USADO":
        return "pre_owned"
    return "retail"


def map_sub_order_type(row: Dict[str, Any]) -> str:
    tipo = (clean(row.get("TipoVta")) or "").upper()
    if "INTER" in tipo:
        return "exchange"
    if "CRED" in tipo:
        return "bank"
    return "out_right"


def parse_order(row: Dict[str, Any], organization: str) -> Optional[Dict[str, Any]]:
    invoice_no = clean(row.get("Factura"))
    customer_id = customer_id_from_row(row)
    vehicle_id = clean(row.get("NoSerie"))
    if not invoice_no or not customer_id or not vehicle_id:
        return None

    order: Dict[str, Any] = {
        "id": invoice_no,
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "invoice_no": invoice_no,
        "organization": organization,
        "reference": clean(row.get("Pedido")),
        "transaction_type": map_transaction_type(row),
        "sub_order_type": map_sub_order_type(row),
        "status": "pending",
        "metadata": {
            "source": "VENTAS UNIVERSIDAD",
            "cfdi_uuid": clean(row.get("uuidventa")),
            "cpny_id": clean(row.get("CpnyID")),
            "sucursal": clean(row.get("SUCURSAL")),
            "tipo_vta": clean(row.get("TipoVta")),
            "seller_name": clean(row.get("Vendedor")),
            "seller_id": clean(row.get("NoVendedor")),
        },
    }

    invoice_date = parse_datetime_iso(row.get("FechaFact"))
    if invoice_date:
        order["invoice_date"] = invoice_date
        order["transaction_date"] = invoice_date.split("T", 1)[0]

    for target, source in (
        ("subtotal", "subtotal"),
        ("iva", "iva"),
        ("isan", "Isan"),
        ("total", "Total"),
    ):
        amount = safe_money(row.get(source))
        if amount is not None:
            order[target] = amount

    seller_id = clean(row.get("NoVendedor"))
    if seller_id:
        order["seller_id"] = seller_id

    return order


def payment_id_from_row(row: Dict[str, Any]) -> Optional[str]:
    invoice_no = clean(row.get("Factura"))
    uuid_pago = clean(row.get("uuidPago"))
    serie = clean(row.get("serie"))
    folio = clean(row.get("folio"))
    if uuid_pago and invoice_no:
        return compact_id(f"{uuid_pago.upper()}-{invoice_no}")
    if serie and folio and invoice_no:
        return compact_id(f"{serie}-{folio}-{invoice_no}")
    return None


def parse_payment(row: Dict[str, Any], organization: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    invoice_no = clean(row.get("Factura"))
    payment_id = payment_id_from_row(row)
    if not invoice_no:
        return None, "missing_order_id"
    if not payment_id:
        return None, "missing_payment_id"

    amount = safe_money(row.get("pago"))
    if amount is None:
        return None, "invalid_amount"
    if abs(amount) < 0.01:
        return None, "zero_amount"

    payment_form = normalize_sat_code(row.get("MetodoDePago"))
    uuid_pago = clean(row.get("uuidPago"))
    payment: Dict[str, Any] = {
        "id": payment_id,
        "salt": payment_id,
        "order_id": f"{invoice_no}|{invoice_no}",
        "organization": organization,
        "payment_form": payment_form,
        "payment_type": "internal",
        "cfdi_conceptual_type": "payment_receipt",
        "amount": amount,
        "total": amount,
        "invoice_id": invoice_no,
        "invoice_uuid": clean(row.get("uuidventa")),
        "series": clean(row.get("serie")),
        "folio": clean(row.get("folio")),
        "uuid": uuid_pago,
        "payment_uuid": uuid_pago,
        "rfc": clean(row.get("Rfc")),
        "customer_id": customer_id_from_row(row),
        "vehicle_id": clean(row.get("NoSerie")),
    }

    payment_date = parse_datetime_iso(row.get("fechaTimbrePago"))
    if payment_date:
        payment["date"] = payment_date

    serie = clean(row.get("serie"))
    folio = clean(row.get("folio"))
    if serie or folio:
        payment["operation_reference"] = "-".join(part for part in (serie, folio) if part)

    return payment, None


def build_order_entities(
    rows: Sequence[Dict[str, Any]],
    organization_override: Optional[str] = None,
    organization_mode: str = "sucursal-cpny",
    include_cancelled: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    vehicles: Dict[str, Dict[str, Any]] = {}
    customers: Dict[Tuple[str, str], Dict[str, Any]] = {}
    orders: Dict[str, Dict[str, Any]] = {}
    stats = {
        "total_rows": len(rows),
        "cancelled_rows": 0,
        "skipped_cancelled": 0,
        "missing_vehicle": 0,
        "missing_customer": 0,
        "missing_order": 0,
        "vehicles": 0,
        "customers": 0,
        "orders": 0,
    }

    for row in rows:
        cancelled = is_cancelled_row(row)
        if cancelled:
            stats["cancelled_rows"] += 1
            if not include_cancelled:
                stats["skipped_cancelled"] += 1
                continue

        organization = organization_from_row(row, organization_override, organization_mode)
        vehicle = parse_vehicle(row, organization)
        customer = parse_customer(row, organization)
        order = parse_order(row, organization)

        if vehicle and vehicle.get("id"):
            vehicles[vehicle["id"]] = vehicle
        else:
            stats["missing_vehicle"] += 1

        if customer and customer.get("id"):
            customers[(customer["id"], organization)] = customer
        else:
            stats["missing_customer"] += 1

        if order and order.get("id"):
            orders[order["id"]] = order
        else:
            stats["missing_order"] += 1

    stats["vehicles"] = len(vehicles)
    stats["customers"] = len(customers)
    stats["orders"] = len(orders)
    return list(vehicles.values()), list(customers.values()), list(orders.values()), stats


def build_payment_payloads(
    rows: Sequence[Dict[str, Any]],
    organization_override: Optional[str] = None,
    organization_mode: str = "sucursal-cpny",
    include_cancelled: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    stats = {
        "total_rows": len(rows),
        "cancelled_rows": 0,
        "skipped_cancelled": 0,
        "prepared": 0,
        "missing_order_id": 0,
        "missing_payment_id": 0,
        "invalid_amount": 0,
        "zero_amount": 0,
        "duplicate": 0,
    }
    payments: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()

    for row in rows:
        cancelled = is_cancelled_row(row)
        if cancelled:
            stats["cancelled_rows"] += 1
            if not include_cancelled:
                stats["skipped_cancelled"] += 1
                continue

        organization = organization_from_row(row, organization_override, organization_mode)
        payment, reason = parse_payment(row, organization)
        if payment is None:
            if reason in stats:
                stats[reason] += 1
            continue

        key = (
            clean(payment.get("id")) or "",
            clean(payment.get("order_id")) or "",
            clean(payment.get("organization")) or "",
        )
        if key in seen:
            stats["duplicate"] += 1
            continue
        seen.add(key)
        payments.append(payment)
        stats["prepared"] += 1

    payments.sort(key=lambda item: (item.get("order_id", ""), item.get("date", ""), item.get("id", "")))
    return payments, stats


def build_order_route_id(
    row: Dict[str, Any],
    organization_override: Optional[str] = None,
    organization_mode: str = "sucursal-cpny",
) -> Optional[str]:
    invoice_no = clean(row.get("Factura"))
    if not invoice_no:
        return None
    organization = organization_from_row(row, organization_override, organization_mode)
    return f"{invoice_no}|{invoice_no}~{organization}"


def build_payment_route_id(
    row: Dict[str, Any],
    organization_override: Optional[str] = None,
    organization_mode: str = "sucursal-cpny",
) -> Optional[str]:
    payment_id = payment_id_from_row(row)
    if not payment_id:
        return None
    organization = organization_from_row(row, organization_override, organization_mode)
    return f"{payment_id}|{payment_id}~{organization}"


def build_order_cancellation_targets(
    rows: Sequence[Dict[str, Any]],
    organization_override: Optional[str] = None,
    organization_mode: str = "sucursal-cpny",
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    targets: List[Dict[str, str]] = []
    seen: set[str] = set()
    stats = {
        "total_rows": len(rows),
        "active_rows": 0,
        "cancelled_rows": 0,
        "missing_order_id": 0,
        "duplicate_target": 0,
        "prepared": 0,
    }

    for row in rows:
        if not is_cancelled_row(row):
            stats["active_rows"] += 1
            continue
        stats["cancelled_rows"] += 1

        route_id = build_order_route_id(row, organization_override, organization_mode)
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
                "order_id": clean(row.get("Factura")) or "",
                "cancel_date": parse_date_ymd(row.get("fechacanc")) or "",
                "reason": clean(row.get("Cancelacion")) or "cancelled",
            }
        )
        stats["prepared"] += 1

    return targets, stats


def build_payment_cancellation_targets(
    rows: Sequence[Dict[str, Any]],
    organization_override: Optional[str] = None,
    organization_mode: str = "sucursal-cpny",
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    targets: List[Dict[str, str]] = []
    seen: set[str] = set()
    stats = {
        "total_rows": len(rows),
        "active_rows": 0,
        "cancelled_rows": 0,
        "missing_payment_id": 0,
        "duplicate_target": 0,
        "prepared": 0,
    }

    for row in rows:
        if not is_cancelled_row(row):
            stats["active_rows"] += 1
            continue
        stats["cancelled_rows"] += 1

        route_id = build_payment_route_id(row, organization_override, organization_mode)
        if route_id is None:
            stats["missing_payment_id"] += 1
            continue
        if route_id in seen:
            stats["duplicate_target"] += 1
            continue
        seen.add(route_id)
        targets.append(
            {
                "route_id": route_id,
                "payment_id": payment_id_from_row(row) or "",
                "order_id": clean(row.get("Factura")) or "",
                "cancel_date": parse_date_ymd(row.get("fechacanc")) or "",
                "reason": clean(row.get("Cancelacion")) or "cancelled",
            }
        )
        stats["prepared"] += 1

    return targets, stats


def column_index(cell_ref: str) -> int:
    letters = re.match(r"([A-Z]+)", cell_ref).group(1)
    value = 0
    for char in letters:
        value = value * 26 + ord(char) - 64
    return value


def read_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(data)
    strings = []
    for item in root.findall("main:si", XLSX_NS):
        strings.append("".join(text.text or "" for text in item.findall(".//main:t", XLSX_NS)))
    return strings


def first_sheet_path(zf: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("pkgrel:Relationship", XLSX_NS)
    }
    sheet = workbook.find("main:sheets/main:sheet", XLSX_NS)
    if sheet is None:
        raise ValueError("Workbook does not contain sheets")
    rid = sheet.attrib[f"{{{XLSX_NS['rel']}}}id"]
    target = targets[rid]
    if not target.startswith("xl/"):
        target = "xl/" + target
    return target


def xlsx_cell_value(cell: ET.Element, shared_strings: Sequence[str]) -> Any:
    cell_type = cell.attrib.get("t")
    value = cell.find("main:v", XLSX_NS)
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//main:t", XLSX_NS))
    if value is None:
        return None
    raw = value.text
    if cell_type == "s":
        return shared_strings[int(raw)]
    if cell_type == "b":
        return raw == "1"
    return raw


def read_xlsx_rows(path: str) -> List[Dict[str, Any]]:
    with zipfile.ZipFile(path) as zf:
        shared_strings = read_shared_strings(zf)
        sheet_path = first_sheet_path(zf)
        root = ET.fromstring(zf.read(sheet_path))

    parsed_rows: List[Dict[int, Any]] = []
    for row in root.findall("main:sheetData/main:row", XLSX_NS):
        parsed: Dict[int, Any] = {}
        for cell in row.findall("main:c", XLSX_NS):
            parsed[column_index(cell.attrib["r"])] = xlsx_cell_value(cell, shared_strings)
        parsed_rows.append(parsed)

    if not parsed_rows:
        return []

    header_row = parsed_rows[0]
    headers = [clean(header_row.get(idx)) for idx in range(1, max(header_row) + 1)]
    rows: List[Dict[str, Any]] = []
    for raw in parsed_rows[1:]:
        row: Dict[str, Any] = {}
        for idx, header in enumerate(headers, start=1):
            if header:
                row[header] = clean(raw.get(idx))
        rows.append(row)
    return rows


def validate_sql_reference(reference: str) -> str:
    if not SQL_REFERENCE_RE.fullmatch(reference):
        raise ValueError(
            f"Unsafe SQL table/view reference: {reference!r}. Use schema.table or [db].[schema].[table]."
        )
    return reference


def quote_sql_identifier(identifier: str) -> str:
    if not SQL_IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f"[{identifier}]"


def build_table_query(
    table: str,
    date_field: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    source_limit: Optional[int] = None,
    sucursal: Optional[str] = None,
    cpny_id: Optional[str] = None,
) -> Tuple[str, List[Any]]:
    table_ref = validate_sql_reference(table)
    select = "SELECT"
    if source_limit is not None:
        select += f" TOP ({int(source_limit)})"
    query = f"{select} * FROM {table_ref}"
    params: List[Any] = []
    conditions: List[str] = []
    if date_field and from_date:
        conditions.append(f"{quote_sql_identifier(date_field)} >= ?")
        params.append(from_date)
    if date_field and to_date:
        conditions.append(f"{quote_sql_identifier(date_field)} < DATEADD(day, 1, ?)")
        params.append(to_date)
    if sucursal:
        conditions.append("LTRIM(RTRIM([SUCURSAL])) = ?")
        params.append(sucursal)
    if cpny_id:
        conditions.append("LTRIM(RTRIM([CpnyID])) = ?")
        params.append(cpny_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    return query, params


def fetch_odbc_rows(connection_string: str, query: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    try:
        import pyodbc  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyodbc is required for ODBC reads. Install pyodbc or use --xlsx.") from exc

    rows: List[Dict[str, Any]] = []
    conn = pyodbc.connect(connection_string)
    try:
        cursor = conn.cursor()
        cursor.execute(query, *(params or []))
        columns = [column[0] for column in cursor.description]
        for record in cursor.fetchall():
            rows.append(dict(zip(columns, record)))
    finally:
        conn.close()
    return rows


def filter_rows_by_date(
    rows: Sequence[Dict[str, Any]],
    date_field: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
) -> List[Dict[str, Any]]:
    if not date_field or (not from_date and not to_date):
        return list(rows)

    filtered: List[Dict[str, Any]] = []
    for row in rows:
        parsed = parse_date_ymd(row.get(date_field))
        if not parsed:
            continue
        if from_date and parsed < from_date:
            continue
        if to_date and parsed > to_date:
            continue
        filtered.append(row)
    return filtered


def filter_rows_by_source_values(
    rows: Sequence[Dict[str, Any]],
    sucursal: Optional[str],
    cpny_id: Optional[str],
) -> List[Dict[str, Any]]:
    filtered = list(rows)
    if sucursal:
        expected = sucursal.strip().upper()
        filtered = [
            row for row in filtered if (clean(row.get("SUCURSAL")) or "").upper() == expected
        ]
    if cpny_id:
        expected = cpny_id.strip().upper()
        filtered = [
            row for row in filtered if (clean(row.get("CpnyID")) or "").upper() == expected
        ]
    return filtered


def load_source_rows(args: Any, default_date_field: str) -> List[Dict[str, Any]]:
    date_field = args.date_field or default_date_field

    if args.xlsx:
        print(f"Loading rows from workbook: {args.xlsx}")
        rows = read_xlsx_rows(args.xlsx)
        rows = filter_rows_by_source_values(rows, args.sucursal, args.cpny_id)
        rows = filter_rows_by_date(rows, date_field, args.from_date, args.to_date)
        if args.source_limit is not None:
            rows = rows[: args.source_limit]
        print(f"Loaded {len(rows)} row(s)")
        return rows

    if not args.connection_string:
        raise ValueError("Provide --xlsx or --connection-string/UNIVERSIDAD_ODBC_CONNECTION_STRING")

    if args.query_file:
        with open(args.query_file, "r", encoding="utf-8") as handle:
            query = handle.read()
        params: List[Any] = []
    elif args.query:
        query = args.query
        params = []
    elif args.table:
        query, params = build_table_query(
            table=args.table,
            date_field=date_field,
            from_date=args.from_date,
            to_date=args.to_date,
            source_limit=args.source_limit,
            sucursal=args.sucursal,
            cpny_id=args.cpny_id,
        )
    else:
        raise ValueError("Provide --table, --query, or --query-file for ODBC reads")

    print("Loading rows through ODBC")
    print(f"Query: {query}")
    rows = fetch_odbc_rows(args.connection_string, query, params)
    if args.query or args.query_file:
        rows = filter_rows_by_source_values(rows, args.sucursal, args.cpny_id)
        rows = filter_rows_by_date(rows, date_field, args.from_date, args.to_date)
        if args.source_limit is not None:
            rows = rows[: args.source_limit]
    print(f"Loaded {len(rows)} row(s)")
    return rows


def add_source_args(parser: Any, default_date_field: str) -> None:
    parser.add_argument("--xlsx", default=os.getenv("UNIVERSIDAD_XLSX"), help="Read rows from an .xlsx export")
    parser.add_argument(
        "--connection-string",
        default=os.getenv("UNIVERSIDAD_ODBC_CONNECTION_STRING"),
        help="ODBC connection string for SQL Server",
    )
    parser.add_argument(
        "--table",
        default=os.getenv("UNIVERSIDAD_SOURCE_TABLE"),
        help="SQL Server table/view containing the flattened VENTAS UNIVERSIDAD columns",
    )
    parser.add_argument(
        "--query",
        default=os.getenv("UNIVERSIDAD_SOURCE_QUERY"),
        help="Custom SQL query that returns the flattened VENTAS UNIVERSIDAD columns",
    )
    parser.add_argument("--query-file", help="File containing a custom SQL query")
    parser.add_argument("--date-field", default=default_date_field, help="Source date column used for date filters")
    parser.add_argument("--from-date", help="Filter source rows from YYYY-MM-DD")
    parser.add_argument("--to-date", help="Filter source rows through YYYY-MM-DD")
    parser.add_argument("--sucursal", default=os.getenv("UNIVERSIDAD_SUCURSAL"), help="Filter rows by SUCURSAL")
    parser.add_argument("--cpny-id", default=os.getenv("UNIVERSIDAD_CPNY_ID"), help="Filter rows by CpnyID")
    parser.add_argument("--source-limit", type=int, help="Maximum rows to fetch/read before transformation")


def add_api_args(parser: Any) -> None:
    parser.add_argument("--api-base", default=os.getenv("PRESA_API_BASE", API_BASE_DEFAULT))
    parser.add_argument("--tenant-id", default=os.getenv("PRESA_TENANT_ID"))
    parser.add_argument("--client-id", default=os.getenv("PRESA_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.getenv("PRESA_CLIENT_SECRET"))
    parser.add_argument(
        "--organization",
        default=os.getenv("UNIVERSIDAD_ORGANIZATION"),
        help="Override organization id; otherwise uses SUCURSAL--CpnyID",
    )
    parser.add_argument(
        "--organization-mode",
        choices=("sucursal-cpny", "sucursal"),
        default=os.getenv("UNIVERSIDAD_ORGANIZATION_MODE", "sucursal-cpny"),
        help="Organization mapping when --organization is not set",
    )


def require_auth_args(args: Any) -> None:
    missing = [
        name
        for name in ("tenant_id", "client_id", "client_secret")
        if not getattr(args, name, None)
    ]
    if missing:
        raise ValueError(
            "Missing API auth values: "
            + ", ".join("--" + name.replace("_", "-") for name in missing)
            + " (or PRESA_TENANT_ID/PRESA_CLIENT_ID/PRESA_CLIENT_SECRET)"
        )


class TokenManager:
    def __init__(self, api_base: str, tenant_id: str, client_id: str, client_secret: str) -> None:
        self.api_base = api_base.rstrip("/")
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._token_time: Optional[float] = None

    def get_token(self) -> str:
        now = time.time()
        if (
            self._token is None
            or self._token_time is None
            or now - self._token_time > TOKEN_REFRESH_SECONDS
        ):
            self._refresh_token()
        return self._token or ""

    def _refresh_token(self) -> None:
        import requests

        print("\nFetching fresh auth token...")
        response = requests.post(
            f"{self.api_base}/auth/login",
            headers={"tenant_id": self.tenant_id, "tenant": self.tenant_id},
            json={"client_id": self.client_id, "client_secret": self.client_secret},
            timeout=30,
        )
        data = response.json()
        if data.get("status_code") != 200:
            raise RuntimeError(f"Auth failed: {data}")
        self._token = data["data"]["token"]
        self._token_time = time.time()
        print(f"Got token (expires in {data['data']['expires_in']}s)")

    def headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "Authorization": self.get_token()}


class JsonProgress:
    def __init__(self, filename: str, keys: Iterable[str]) -> None:
        self.filename = filename
        self.keys = list(keys)
        self.data = self._load()

    def _load(self) -> Dict[str, List[str]]:
        try:
            with open(self.filename, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            data = {}
        except Exception:
            data = {}
        for key in self.keys:
            data.setdefault(key, [])
        if os.path.exists(self.filename):
            loaded = ", ".join(f"{key}={len(data.get(key, []))}" for key in self.keys)
            print(f"Loaded progress from {self.filename} ({loaded})")
        return data

    def _save(self) -> None:
        with open(self.filename, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle)

    def contains(self, key: str, item_id: str) -> bool:
        return item_id in self.data[key]

    def add(self, key: str, item_id: str) -> None:
        if item_id not in self.data[key]:
            self.data[key].append(item_id)
            self._save()


def progress_item_id(endpoint: str, item: Dict[str, Any]) -> str:
    item_id = clean(item.get("id")) or "<missing-id>"
    organization = clean(item.get("organization"))
    if endpoint == "customers" and item_id != "<missing-id>" and organization:
        return f"{item_id}~{organization}"
    return item_id


def backend_lookup_endpoint(endpoint: str) -> Optional[str]:
    if endpoint in {"customers", "orders", "payments"}:
        return endpoint
    return None


async def backend_item_exists(
    session: aiohttp.ClientSession,
    api_base: str,
    endpoint: str,
    item: Dict[str, Any],
    token_manager: TokenManager,
) -> Tuple[Optional[bool], Optional[int], Any]:
    lookup_endpoint = backend_lookup_endpoint(endpoint)
    if lookup_endpoint is None:
        return None, None, None

    item_id = clean(item.get("id"))
    if not item_id:
        return None, None, None

    params: Dict[str, str] = {}
    organization = clean(item.get("organization"))
    if organization:
        params["organization"] = organization

    url = f"{api_base.rstrip('/')}/{lookup_endpoint}/{quote(item_id, safe='')}"
    try:
        async with session.get(url, headers=token_manager.headers(), params=params) as response:
            text = await response.text()
            try:
                response_data = json.loads(text)
            except Exception:
                response_data = text
            if response.status == 200:
                return True, response.status, response_data
            if response.status == 404:
                return False, response.status, response_data
            return None, response.status, response_data
    except Exception as exc:
        return None, None, str(exc)


async def post_payload(
    session: aiohttp.ClientSession,
    api_base: str,
    endpoint: str,
    payload: Dict[str, Any],
    token_manager: TokenManager,
    verbose: bool = False,
) -> Tuple[bool, Any, Optional[int]]:
    headers = token_manager.headers()
    if verbose:
        print(f"  [{endpoint}] Payload:\n{json.dumps(payload, indent=2, default=str)}")
    try:
        async with session.post(f"{api_base.rstrip('/')}/{endpoint}", headers=headers, json=payload) as response:
            text = await response.text()
            try:
                response_data = json.loads(text)
            except Exception:
                response_data = text
            ok = 200 <= response.status < 300
            return ok, response_data, response.status
    except Exception as exc:
        return False, str(exc), None


async def send_entity_batches(
    api_base: str,
    token_manager: TokenManager,
    db_key: str,
    vehicles: Sequence[Dict[str, Any]],
    customers: Sequence[Dict[str, Any]],
    orders: Sequence[Dict[str, Any]],
    batch_size: int,
    verbose: bool = False,
) -> Dict[str, Dict[str, int]]:
    progress = JsonProgress(f"progress_universidad_{db_key}_live.json", ("vehicles", "customers", "orders"))
    token_manager.get_token()
    totals = {
        "vehicles": {"sent": 0, "skipped": 0, "errors": 0},
        "customers": {"sent": 0, "skipped": 0, "errors": 0},
        "orders": {"sent": 0, "skipped": 0, "errors": 0},
    }

    async with aiohttp.ClientSession() as session:
        for endpoint, payloads in (
            ("vehicles", vehicles),
            ("customers", customers),
            ("orders", orders),
        ):
            print(f"\n=== SENDING {endpoint.upper()} ===")
            total_batches = (len(payloads) + batch_size - 1) // batch_size
            for start in range(0, len(payloads), batch_size):
                batch = payloads[start : start + batch_size]
                batch_num = (start // batch_size) + 1
                print(f"Sending batch {batch_num}/{total_batches} to {endpoint} ({len(batch)} item(s))")
                for idx, item in enumerate(batch, start=1):
                    item_id = progress_item_id(endpoint, item)
                    exists, lookup_status, lookup_data = await backend_item_exists(
                        session, api_base, endpoint, item, token_manager
                    )
                    if exists is True:
                        print(f"  [{endpoint}] Item {idx} (id={item_id}): SKIPPED (exists in backend)")
                        totals[endpoint]["skipped"] += 1
                        continue
                    if exists is None and backend_lookup_endpoint(endpoint) is not None:
                        print(
                            f"  [{endpoint}] Item {idx} (id={item_id}): "
                            f"GET check failed ({lookup_status}) - {lookup_data}"
                        )
                        totals[endpoint]["errors"] += 1
                        continue
                    if (
                        backend_lookup_endpoint(endpoint) is None
                        and item_id != "<missing-id>"
                        and progress.contains(endpoint, item_id)
                    ):
                        print(f"  [{endpoint}] Item {idx} (id={item_id}): SKIPPED")
                        totals[endpoint]["skipped"] += 1
                        continue
                    ok, response_data, status = await post_payload(
                        session, api_base, endpoint, item, token_manager, verbose
                    )
                    print(f"  [{endpoint}] Item {idx} (id={item_id}): {status} - {response_data}")
                    if ok:
                        totals[endpoint]["sent"] += 1
                        if item_id != "<missing-id>":
                            progress.add(endpoint, item_id)
                    else:
                        totals[endpoint]["errors"] += 1
                await asyncio.sleep(BATCH_DELAY_SECONDS)
    return totals


async def send_payment_batches(
    api_base: str,
    token_manager: TokenManager,
    db_key: str,
    payments: Sequence[Dict[str, Any]],
    batch_size: int,
    verbose: bool = False,
) -> Dict[str, int]:
    progress = JsonProgress(f"progress_universidad_payments_{db_key}_live.json", ("payments",))
    token_manager.get_token()
    totals = {"sent": 0, "skipped": 0, "errors": 0}
    throttle_state: Dict[str, Any] = {"last_order_id": None, "last_post_ts": None}

    async with aiohttp.ClientSession() as session:
        total_batches = (len(payments) + batch_size - 1) // batch_size
        for start in range(0, len(payments), batch_size):
            batch = payments[start : start + batch_size]
            batch_num = (start // batch_size) + 1
            print(f"Sending batch {batch_num}/{total_batches} to payments ({len(batch)} item(s))")
            for idx, payment in enumerate(batch, start=1):
                payment_id = clean(payment.get("id")) or "<missing-id>"
                exists, lookup_status, lookup_data = await backend_item_exists(
                    session, api_base, "payments", payment, token_manager
                )
                if exists is True:
                    print(f"  [payments] Item {idx} (id={payment_id}): SKIPPED (exists in backend)")
                    totals["skipped"] += 1
                    continue
                if exists is None:
                    print(
                        f"  [payments] Item {idx} (id={payment_id}): "
                        f"GET check failed ({lookup_status}) - {lookup_data}"
                    )
                    totals["errors"] += 1
                    continue

                current_order_id = clean(payment.get("order_id"))
                if (
                    current_order_id
                    and current_order_id == throttle_state.get("last_order_id")
                    and isinstance(throttle_state.get("last_post_ts"), float)
                ):
                    elapsed = time.monotonic() - throttle_state["last_post_ts"]
                    wait_seconds = SAME_ORDER_PAYMENT_DELAY_SECONDS - elapsed
                    if wait_seconds > 0:
                        print(f"  [payments] Same order detected, waiting {wait_seconds:.2f}s")
                        await asyncio.sleep(wait_seconds)

                ok, response_data, status = await post_payload(
                    session, api_base, "payments", payment, token_manager, verbose
                )
                print(f"  [payments] Item {idx} (id={payment_id}): {status} - {response_data}")
                if ok:
                    totals["sent"] += 1
                    if payment_id != "<missing-id>":
                        progress.add("payments", payment_id)
                else:
                    totals["errors"] += 1
                throttle_state["last_order_id"] = current_order_id
                throttle_state["last_post_ts"] = time.monotonic()
            await asyncio.sleep(BATCH_DELAY_SECONDS)
    return totals


async def cancel_targets(
    api_base: str,
    token_manager: TokenManager,
    db_key: str,
    endpoint: str,
    targets: Sequence[Dict[str, str]],
    batch_size: int,
    verbose: bool = False,
) -> Dict[str, int]:
    progress = JsonProgress(
        f"progress_universidad_cancel_{endpoint}_{db_key}_live.json",
        ("cancelled",),
    )
    token_manager.get_token()
    totals = {"cancelled": 0, "skipped": 0, "errors": 0}

    async with aiohttp.ClientSession() as session:
        total_batches = (len(targets) + batch_size - 1) // batch_size
        for start in range(0, len(targets), batch_size):
            batch = targets[start : start + batch_size]
            batch_num = (start // batch_size) + 1
            print(f"Sending cancel batch {batch_num}/{total_batches} to {endpoint} ({len(batch)} item(s))")
            for idx, target in enumerate(batch, start=1):
                route_id = target["route_id"]
                if progress.contains("cancelled", route_id):
                    print(f"  [{endpoint}-cancel] Item {idx} (route_id={route_id}): SKIPPED")
                    totals["skipped"] += 1
                    continue

                encoded_id = quote(route_id, safe="")
                url = f"{api_base.rstrip('/')}/{endpoint}/{encoded_id}/cancel"
                headers = token_manager.headers()
                if verbose:
                    print(f"  [{endpoint}-cancel] Target {idx}: {json.dumps(target, indent=2)}")
                try:
                    async with session.post(url, headers=headers, json={}) as response:
                        text = await response.text()
                        try:
                            response_data = json.loads(text)
                        except Exception:
                            response_data = text
                        print(f"  [{endpoint}-cancel] Item {idx} (route_id={route_id}): {response.status} - {response_data}")
                        if 200 <= response.status < 300:
                            progress.add("cancelled", route_id)
                            totals["cancelled"] += 1
                        else:
                            totals["errors"] += 1
                except Exception as exc:
                    print(f"  [{endpoint}-cancel] Error on item {idx} (route_id={route_id}): {exc}")
                    totals["errors"] += 1
            await asyncio.sleep(BATCH_DELAY_SECONDS)
    return totals
