#!/usr/bin/env python3
"""Shared helpers for the Refran SQL Server order feed."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

import aiohttp

from universidad_common import (
    API_BASE_DEFAULT,
    BATCH_DELAY_SECONDS,
    JsonProgress,
    TokenManager,
    clean,
    parse_date_ymd,
    post_payload,
    require_auth_args,
    safe_money,
)


DEFAULT_TENANT_ID = "refran"
DEFAULT_TRANSACTION_TYPES = ("retail", "exchange")
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

STATE_MAP = {
    "01": "AGUASCALIENTES",
    "02": "BAJA CALIFORNIA",
    "03": "BAJA CALIFORNIA SUR",
    "04": "CAMPECHE",
    "05": "COAHUIL",
    "06": "COLIMA",
    "07": "CHIAPAS",
    "08": "CHIHUAHUA",
    "09": "CIUDAD DE MEXICO",
    "10": "DURANGO",
    "11": "GUANAJUATO",
    "12": "GUERRERO",
    "13": "HIDALGO",
    "14": "JALISCO",
    "15": "MEXICO",
    "16": "MICHOACAN",
    "17": "MORELOS",
    "18": "NAYARIT",
    "19": "NUEVO LEON",
    "20": "OAXACA",
    "21": "PUEBLA",
    "22": "QUERETARO",
    "23": "QUINTANA ROO",
    "24": "SAN LUIS POTOSI",
    "25": "SINALOA",
    "26": "SONORA",
    "27": "TABASCO",
    "28": "TAMAULIPAS",
    "29": "TLAXCALA",
    "30": "VERACRUZ",
    "31": "YUCATAN",
    "32": "ZACATECAS",
}

VEHICLE_LINE_MAP = {
    "01": "CAMION/PICK UP",
    "02": "CAMIONETA",
    "03": "CHASIS CABINA",
    "04": "COMPACTOS",
    "05": "CONVERTIBLE",
    "06": "COUPE",
    "07": "CROSSOVER",
    "08": "HATCHBACK",
    "09": "MINIVAN",
    "10": "SEDAN",
    "11": "SMALL PICK UP",
    "12": "SUV",
    "13": "WAGONS",
    "5P": "5P",
    "CAM": "CAMIONES",
    "CAR": "CARGO",
    "COM": "COMPACTO",
    "DEP": "DEPORTIVO",
    "DEU": "DEPORTIVO UTILITARIO",
    "DLJ": "LUJO",
    "FAA": "FAMILIAR ALTO",
    "FAB": "FAMILIAR BAJO",
    "FAM": "FAMILIAR",
    "FDL": "FAMILIAR DE LUJO",
    "FOU": "FOURGON",
    "JUV": "JUVENIL",
    "LIG": "LIGEROS",
    "LIL": "LIGERO LUJO",
    "MAP": "MAXI PACK",
    "MAX": "MAXI",
    "MED": "MEDIANO",
    "MIN": "MINI",
    "PEQ": "PEQUENOS",
    "POP": "POPULAR",
    "REG": "REGULAR",
    "SEDAN": "SEDAN",
    "SLJ": "SUPER LUJO",
    "SUVS": "SUV",
    "TRA": "TRABAJO",
    "UTC": "UTILITARIOS CORTOS",
    "UTL": "UTILITARIOS LARGOS",
    "UTM": "UTILITARIOS MEDIANOS",
    "VAN": "VANS",
    "VNC": "VANS/COMERCIALES",
}

SUB_ORDER_TYPE_MAP = {
    "01": "bank",
    "02": "fleet",
    "02MT": "fleet",
    "02SN": "fleet",
    "02GS": "fleet",
    "03": "employee",
    "04": "out_right",
    "05": "fleet",
    "05MT": "fleet",
    "05GS": "fleet",
    "05SN": "fleet",
    "06": "fleet",
    "07": "employee",
    "08": "employee",
    "09": "out_right",
    "20": "employee",
    "21": "employee",
    "22": "employee",
    "COLISION": "total_loss",
    "PERDIDA": "total_loss",
    "PLNCON": "out_right",
    "PLNCONMT": "out_right",
    "PLNCONSN": "out_right",
    "PLNCONGS": "out_right",
    "VENTAMRS": "exchange",
    "VTACON": "out_right",
}

SELLER_ID_MAP = {
    "141": "XXX",
    "146": "RRO",
    "156": "ANM",
    "157": "ORR",
    "158": "MHV",
    "159": "VGJ",
    "160": "GRJ",
    "6451": "VHO",
    "14125": "FCJ",
    "15926": "HAK",
    "15945": "HGV",
    "15948": "FPS",
    "15954": "MRV",
    "15955": "CLJ",
    "97359": "XXX",
    "97641": "HLA",
    "97642": "PPA",
    "97643": "EGA",
    "97644": "ARD",
    "97646": "CCG0",
    "97648": "CAT",
    "97649": "CGM",
    "97653": "AZG",
    "99977": "LHJ",
    "102656": "OML",
    "123776": "MCM",
    "124230": "RSR",
    "175681": "HDJ",
    "187212": "CSJ",
    "197757": "GMJ3",
    "208098": "HRC",
    "219155": "CGM0",
    "239603": "CAC",
    "239814": "GRT",
    "261470": "CVN",
    "281648": "MAH",
    "332157": "CAJ0",
    "353159": "GMJ4",
    "353160": "HMG0",
    "353246": "PRS",
    "353277": "ZCH",
    "373467": "MAR",
    "373468": "VGS",
    "424591": "MRL",
    "424592": "RMJ",
    "485779": "GZE",
    "505996": "FEM",
    "697827": "LMJ",
    "708233": "DHC",
    "718572": "FAE",
    "779193": "CCD",
    "830572": "AND",
    "901120": "PGA",
    "901306": "SVA",
    "1042930": "ORN",
    "1083826": "ADM",
    "1084519": "RLC1",
    "1145954": "EVO",
    "1146146": "GSR",
    "1146195": "LVL",
    "1197239": "RLC1",
    "1197386": "REA1",
    "1238793": "RTA",
    "1238883": "GGJ0",
    "1249054": "XXX",
    "7123": "MAR",
    "97651": "SGL",
    "108951": "AZG",
    "342474": "TOA",
    "187211": "CSJ",
    "97650": "GMF",
    "404183": "XXX",
    "175804": "CEJ",
    "373466": "DHC",
    "162": "ASA",
    "163": "CCJ",
    "170": "GNA",
    "171": "CSR",
    "13856": "XXX",
    "15079": "XXX",
    "15392": "SRE",
    "165021": "CSA",
    "165022": "GRS",
    "165026": "GAT",
    "165027": "E1A",
    "239914": "GCL",
    "239915": "JBB",
    "239916": "CMS",
    "239917": "PMZ",
    "260554": "RVJ",
    "342472": "HML",
    "343060": "HMA",
    "353209": "EVO",
    "353235": "PUR",
    "353281": "HMJ",
    "393994": "MLA",
    "393996": "RLJ",
    "404185": "JHC",
    "445071": "EJD",
    "687676": "RPH",
    "819526": "COJ",
    "830709": "PEG",
    "830710": "VBV",
    "880855": "LRK",
    "932003": "BZF",
    "1063361": "GHI",
    "1197892": "PRA",
    "505914": "GZE",
    "992263": "RLL",
    "1269926": "HFL",
    "208046": "JPM",
    "1249411": "SGE0",
}


@dataclass(frozen=True)
class TargetOrder:
    db_name: str
    order_id: str
    transaction_type: str
    operation_date: Optional[str] = None
    source_customer_id: Optional[str] = None
    order_status: Optional[str] = None
    invoice_status: Optional[str] = None


def default_from_date() -> str:
    today = date.today()
    month = today.month - 8
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1).isoformat()


def quote_db_name(db_name: str) -> str:
    if not SQL_IDENTIFIER_RE.fullmatch(db_name):
        raise ValueError(f"Unsafe Refran database name: {db_name!r}")
    return f"[{db_name}]"


def split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,\s]+", value) if part.strip()]


def parse_db_names(raw_values: Optional[Sequence[str]]) -> List[str]:
    raw_items = list(raw_values or [])
    if not raw_items:
        env_value = os.getenv("REFRAN_DATABASES")
        if env_value:
            raw_items = [env_value]

    values: List[str] = []
    for raw in raw_items:
        for chunk in re.split(r"[,\s]+", raw):
            if not chunk:
                continue
            values.extend(part for part in chunk.split("-") if part)

    deduped: List[str] = []
    for value in values:
        if value not in deduped:
            quote_db_name(value)
            deduped.append(value)
    if not deduped:
        raise ValueError("Provide at least one Refran --db value or REFRAN_DATABASES")
    return deduped


def parse_transaction_types(raw: Optional[str]) -> Tuple[str, ...]:
    values = tuple(split_csv(raw) or DEFAULT_TRANSACTION_TYPES)
    invalid = [value for value in values if value not in {"retail", "exchange"}]
    if invalid:
        raise ValueError(f"Unsupported transaction type(s): {', '.join(invalid)}")
    return values


def add_refran_source_args(parser: Any) -> None:
    parser.add_argument(
        "--db",
        action="append",
        help="Refran SQL Server database name. Can be repeated, comma-separated, or hyphen-separated.",
    )
    parser.add_argument(
        "--connection-string",
        default=os.getenv("REFRAN_ODBC_CONNECTION_STRING"),
        help="ODBC connection string for the Refran SQL Server source",
    )
    parser.add_argument(
        "--transaction-types",
        default=os.getenv("REFRAN_TRANSACTION_TYPES", ",".join(DEFAULT_TRANSACTION_TYPES)),
        help="Comma-separated transaction types to read: retail,exchange",
    )
    parser.add_argument("--from-date", help="Filter UPE_FECHOPE from YYYY-MM-DD")
    parser.add_argument("--to-date", help="Filter UPE_FECHOPE through YYYY-MM-DD")
    parser.add_argument(
        "--all-history",
        action="store_true",
        help="Do not apply the default first-day-eight-months-ago source filter",
    )
    parser.add_argument("--source-limit", type=int, help="Maximum source target orders after sorting")


def add_refran_api_args(parser: Any) -> None:
    parser.add_argument("--api-base", default=os.getenv("PRESA_API_BASE", API_BASE_DEFAULT))
    parser.add_argument("--tenant-id", default=os.getenv("PRESA_TENANT_ID", DEFAULT_TENANT_ID))
    parser.add_argument("--client-id", default=os.getenv("PRESA_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.getenv("PRESA_CLIENT_SECRET"))
    parser.add_argument(
        "--organization",
        default=os.getenv("REFRAN_ORGANIZATION"),
        help="Override organization id; otherwise uses the source database name",
    )


def require_source_args(args: Any) -> None:
    if not args.connection_string:
        raise ValueError(
            "Missing --connection-string or REFRAN_ODBC_CONNECTION_STRING for Refran SQL Server"
        )


class RefranSqlServerSource:
    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string

    def fetch_rows(
        self,
        db_name: str,
        query: str,
        params: Optional[Sequence[Any]] = None,
    ) -> List[Dict[str, Any]]:
        try:
            import pyodbc  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyodbc is required for Refran ODBC reads") from exc

        rows: List[Dict[str, Any]] = []
        conn = pyodbc.connect(self.connection_string)
        try:
            cursor = conn.cursor()
            cursor.execute(f"USE {quote_db_name(db_name)}")
            cursor.execute(query, *(params or []))
            columns = [column[0] for column in cursor.description]
            for record in cursor.fetchall():
                rows.append(dict(zip(columns, record)))
        finally:
            conn.close()
        return rows


def date_filter_sql(alias: str, from_date: Optional[str], to_date: Optional[str]) -> Tuple[List[str], List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if from_date:
        clauses.append(f"TRY_CONVERT(date, {alias}.UPE_FECHOPE, 103) >= ?")
        params.append(from_date)
    if to_date:
        clauses.append(f"TRY_CONVERT(date, {alias}.UPE_FECHOPE, 103) < DATEADD(day, 1, ?)")
        params.append(to_date)
    return clauses, params


def active_scan_query(transaction_type: str, from_date: Optional[str], to_date: Optional[str]) -> Tuple[str, List[Any]]:
    sale_filter = "tipocat.PAR_IDENPARA IN ('VENTAMRS', 'VTACON')"
    if transaction_type == "retail":
        sale_filter = "tipocat.PAR_IDENPARA NOT IN ('VENTAMRS', 'VTACON')"
    date_clauses, params = date_filter_sql("upe", from_date, to_date)
    where_clauses = [
        "upe.UPE_STATUS = 'I'",
        "vta.VTE_STATUS = 'I'",
        "tipocat.PAR_TIPOPARA = 'VNT'",
        sale_filter,
        *date_clauses,
    ]
    return (
        f"""
        SELECT DISTINCT
            upe.UPE_IDPEDI AS order_id,
            upe.UPE_FECHOPE AS operation_date,
            per.PER_IDPERSONA AS source_customer_id,
            upe.UPE_STATUS AS order_status,
            vta.VTE_STATUS AS invoice_status
        FROM UNI_PEDIDO upe
        LEFT JOIN [CHRLaredoCon].[dbo].[PER_PERSONAS] per
            ON upe.UPE_IDCLIENTE = per.PER_IDPERSONA
        LEFT JOIN UNI_PEDIUNI upn
            ON upe.UPE_IDPEDI = upn.PEN_IDPEDI
        LEFT JOIN ADE_VTAFI vta
            ON upe.UPE_IDCLIENTE = vta.VTE_IDCLIENTE
            AND upn.PEN_NUMSERIE = vta.VTE_SERIE
        LEFT JOIN PNC_PARAMETR tipocat
            ON CAST(upn.PEN_VENTA AS VARCHAR) = CAST(tipocat.PAR_IDENPARA AS VARCHAR)
        WHERE {" AND ".join(where_clauses)}
        ORDER BY upe.UPE_FECHOPE DESC
        """,
        params,
    )


def cancelled_scan_query(transaction_type: str, from_date: Optional[str], to_date: Optional[str]) -> Tuple[str, List[Any]]:
    sale_filter = "tipocat.PAR_IDENPARA IN ('VENTAMRS', 'VTACON')"
    if transaction_type == "retail":
        sale_filter = "tipocat.PAR_IDENPARA NOT IN ('VENTAMRS', 'VTACON')"
    date_clauses, params = date_filter_sql("upe", from_date, to_date)
    where_clauses = [
        "tipocat.PAR_TIPOPARA = 'VNT'",
        sale_filter,
        "(ISNULL(upe.UPE_STATUS, '') <> 'I' OR ISNULL(vta.VTE_STATUS, '') <> 'I')",
        *date_clauses,
    ]
    return (
        f"""
        SELECT DISTINCT
            upe.UPE_IDPEDI AS order_id,
            upe.UPE_FECHOPE AS operation_date,
            per.PER_IDPERSONA AS source_customer_id,
            upe.UPE_STATUS AS order_status,
            vta.VTE_STATUS AS invoice_status
        FROM UNI_PEDIDO upe
        LEFT JOIN [CHRLaredoCon].[dbo].[PER_PERSONAS] per
            ON upe.UPE_IDCLIENTE = per.PER_IDPERSONA
        LEFT JOIN UNI_PEDIUNI upn
            ON upe.UPE_IDPEDI = upn.PEN_IDPEDI
        LEFT JOIN ADE_VTAFI vta
            ON upe.UPE_IDCLIENTE = vta.VTE_IDCLIENTE
            AND upn.PEN_NUMSERIE = vta.VTE_SERIE
        LEFT JOIN PNC_PARAMETR tipocat
            ON CAST(upn.PEN_VENTA AS VARCHAR) = CAST(tipocat.PAR_IDENPARA AS VARCHAR)
        WHERE {" AND ".join(where_clauses)}
        ORDER BY upe.UPE_FECHOPE DESC
        """,
        params,
    )


def customer_query() -> str:
    return """
        SELECT
            per.PER_TIPO AS customer_type,
            per.PER_EMAIL AS email,
            per.PER_PAIS AS country,
            per.PER_ESTADO AS state,
            per.PER_CIUDAD AS city,
            per.PER_COLONIA AS neighborhood,
            per.PER_CALLE1 AS street,
            per.PER_NUMEXTER AS street_number,
            per.PER_NUMINER AS int_number,
            per.PER_CODPOS AS postal_code,
            per.PER_TELEFONO1 AS phone_number,
            upe.UPE_IDCONTACTO AS source_contact_id,
            per.PER_CPAISNUMTEL AS phone_country_code,
            per.PER_NOMRAZON AS first_name,
            per.PER_PATERNO AS paternal,
            per.PER_MATERNO AS maternal,
            per.PER_IDPERSONA AS customer_id,
            per.PER_RFC AS rfc,
            per.PER_CACTECONOMICA AS economical_activity,
            per.REP_IDPERSONA AS representative_id,
            per.REP_NOMRAZON AS representative_first_name,
            per.REP_PATERNO AS representative_paternal,
            per.REP_MATERNO AS representative_maternal,
            per.REP_FECNAC AS representative_birth_date,
            per.REP_FECHOPE AS representative_registration_date,
            per.REP_RFC AS representative_rfc,
            per.PER_FECHOPE AS registration_date,
            per.PER_CURP AS curp,
            per.PER_FECNAC AS birth_date,
            per.PER_NOMRAZON AS denomination,
            per.PER_FECHACONST AS constitution_date,
            per.PER_TIPMORAL AS moral_type,
            cont.PER_IDPERSONA AS contact_id,
            cont.PER_NOMRAZON AS contact_first_name,
            cont.PER_PATERNO AS contact_paternal,
            cont.PER_MATERNO AS contact_maternal,
            cont.PER_EMAIL AS contact_email,
            cont.PER_TELEFONO1 AS contact_phone_number,
            cont.PER_CPAISNUMTEL AS contact_phone_country_code,
            per.REP_CURP AS representative_curp
        FROM UNI_PEDIDO upe
        LEFT JOIN CHRLaredoCon.dbo.PER_PERSONAS cont
            ON upe.UPE_IDCONTACTO = cont.PER_IDPERSONA
        LEFT JOIN (
            SELECT
                p_fis.PER_IDPERSONA,
                p_fis.PER_RFC,
                p_fis.PER_NOMRAZON,
                p_fis.PER_PATERNO,
                p_fis.PER_MATERNO,
                p_fis.PER_CURP,
                p_fis.PER_FECNAC,
                p_fis.PER_CACTECONOMICA,
                p_fis.PER_EMAIL,
                p_fis.PER_PAIS,
                p_fis.PER_ESTADO,
                p_fis.PER_CIUDAD,
                p_fis.PER_COLONIA,
                p_fis.PER_CALLE1,
                p_fis.PER_NUMEXTER,
                p_fis.PER_NUMINER,
                p_fis.PER_CODPOS,
                p_fis.PER_TELEFONO1,
                p_fis.PER_TELEFONO2,
                p_fis.PER_CPAISNUMTEL,
                p_fis.PER_FECHOPE,
                'FIS' AS PER_TIPO,
                NULL AS PER_TIPMORAL,
                NULL AS PER_FECHACONST,
                NULL AS REP_IDPERSONA,
                NULL AS REP_NOMRAZON,
                NULL AS REP_PATERNO,
                NULL AS REP_MATERNO,
                NULL AS REP_FECNAC,
                NULL AS REP_FECHOPE,
                NULL AS REP_RFC,
                NULL AS REP_CURP
            FROM CHRLaredoCon.dbo.PER_PERSONAS p_fis
            WHERE p_fis.PER_TIPO = 'FIS' OR p_fis.PER_TIPO = 'FIE'
            UNION ALL
            SELECT
                p_mor.PER_IDPERSONA,
                p_mor.PER_RFC,
                p_mor.PER_NOMRAZON,
                NULL AS PER_PATERNO,
                NULL AS PER_MATERNO,
                NULL AS PER_CURP,
                NULL AS PER_FECNAC,
                p_mor.PER_CACTECONOMICA,
                p_mor.PER_EMAIL,
                p_mor.PER_PAIS,
                p_mor.PER_ESTADO,
                p_mor.PER_CIUDAD,
                p_mor.PER_COLONIA,
                p_mor.PER_CALLE1,
                p_mor.PER_NUMEXTER,
                p_mor.PER_NUMINER,
                p_mor.PER_CODPOS,
                p_mor.PER_TELEFONO1,
                p_mor.PER_TELEFONO2,
                p_mor.PER_CPAISNUMTEL,
                p_mor.PER_FECHOPE,
                'MOR' AS PER_TIPO,
                p_mor.PER_TIPMORAL,
                p_mor.PER_FECHACONST,
                rep.PER_IDPERSONA AS REP_IDPERSONA,
                rep.PER_NOMRAZON AS REP_NOMRAZON,
                rep.PER_PATERNO AS REP_PATERNO,
                rep.PER_MATERNO AS REP_MATERNO,
                rep.PER_FECNAC AS REP_FECNAC,
                rep.PER_FECHOPE AS REP_FECHOPE,
                rep.PER_RFC AS REP_RFC,
                rep.PER_CURP AS REP_CURP
            FROM CHRLaredoCon.dbo.PER_PERSONAS p_mor
            LEFT JOIN CHRLaredoCon.dbo.PER_PERSONAS rep
                ON CAST(p_mor.PER_IDREPPERMORAL AS VARCHAR) = CAST(rep.PER_IDPERSONA AS VARCHAR)
            WHERE p_mor.PER_TIPO = 'MOR'
        ) per ON upe.UPE_IDCLIENTE = per.PER_IDPERSONA
        WHERE upe.UPE_IDPEDI = ?
    """


def order_query() -> str:
    return """
        SELECT
            upe.UPE_IDPEDI AS order_id,
            upe.UPE_FECHOPE AS transaction_date,
            vta.VTE_VTABRUT AS subtotal,
            vta.VTE_IVA AS iva,
            vta.VTE_TOTAL AS total,
            vta.VTE_DOCTO AS invoice_no,
            usuagte.PER_IDPERSONA AS seller_id,
            upn.PEN_IDCATALOGO AS catalog_id,
            upn.PEN_MODELO AS catalog_model,
            upn.PEN_NUMSERIE AS serial,
            tipocat.PAR_IDENPARA AS sub_order_source,
            usuagte.PER_NOMRAZON AS seller_first_name,
            usuagte.PER_PATERNO AS seller_paternal,
            usuagte.PER_MATERNO AS seller_maternal,
            upn.PEN_ISAN AS isan
        FROM UNI_PEDIDO upe
        LEFT JOIN UNI_PEDIUNI upn
            ON upe.UPE_IDPEDI = upn.PEN_IDPEDI
        LEFT JOIN ADE_VTAFI vta
            ON upe.UPE_IDCLIENTE = vta.VTE_IDCLIENTE
            AND upn.PEN_NUMSERIE = vta.VTE_SERIE
        LEFT JOIN PER_PERSONAS usuagte
            ON CAST(upe.UPE_IDAGTE AS VARCHAR) = CAST(usuagte.PER_IDPERSONA AS VARCHAR)
        LEFT JOIN PNC_PARAMETR tipocat
            ON CAST(upn.PEN_VENTA AS VARCHAR) = CAST(tipocat.PAR_IDENPARA AS VARCHAR)
        WHERE
            upe.UPE_STATUS = 'I'
            AND upe.UPE_IDPEDI = ?
            AND vta.VTE_STATUS = 'I'
            AND tipocat.PAR_TIPOPARA = 'VNT'
    """


def vehicle_query() -> str:
    return """
        SELECT
            upn.PEN_NUMSERIE AS vehicle_id,
            upn.PEN_MODELO AS year,
            upn.PEN_NUMSERIE AS vin,
            catacolorext.COL_DESCRIPCION AS color,
            cat.UNC_MARCA AS brand,
            cat.UNC_DESCRIPCION AS model,
            vta.VTE_VTABRUT AS msrp,
            upn.PEN_NUMSERIE AS salt,
            vs.VEH_NOINVENTA AS inventory_number,
            catacolorint.COL_DESCRIPCION AS interior_color,
            cat.UNC_CAPACIDAD AS capacity,
            puertas.PAR_DESCRIP1 AS doors,
            cilindros.PAR_DESCRIP1 AS cylinders,
            vs.VEH_NOMOTOR AS motor_origin,
            vs.VEH_ORGUNIDAD AS origin,
            vs.VEH_NOPEDIMTO AS pediment_number,
            vs.VEH_FECPEDIMTO AS pediment_date,
            aduana.PAR_DESCRIP1 AS pediment_custom,
            cat.UNC_IDCATALOGO AS catalog_id,
            cat.UNC_LINEA AS line,
            lineamodelo.PAR_DESCRIP1 AS model_line
        FROM UNI_PEDIUNI upn
        LEFT JOIN UNI_CATALOGO cat
            ON upn.PEN_IDCATALOGO = cat.UNC_IDCATALOGO
            AND upn.PEN_MODELO = cat.UNC_MODELO
        LEFT JOIN UNI_PEDIDO upe
            ON upn.PEN_IDPEDI = upe.UPE_IDPEDI
        LEFT JOIN ADE_VTAFI vta
            ON upe.UPE_IDCLIENTE = vta.VTE_IDCLIENTE
            AND upn.PEN_NUMSERIE = vta.VTE_SERIE
            AND vta.VTE_STATUS = 'I'
        LEFT JOIN SER_VEHICULO vs
            ON upn.PEN_NUMSERIE = vs.VEH_NUMSERIE
        LEFT JOIN UNI_CATACOLOR catacolorint
            ON upn.PEN_MODELO = catacolorint.COL_MODELO
            AND upn.PEN_IDCATALOGO = catacolorint.COL_CATALOGO
            AND catacolorint.COL_TIPO = 'INTERIOR'
            AND vs.VEH_COLOINTE = catacolorint.COL_CLAVE
        LEFT JOIN UNI_CATACOLOR catacolorext
            ON upn.PEN_MODELO = catacolorext.COL_MODELO
            AND upn.PEN_IDCATALOGO = catacolorext.COL_CATALOGO
            AND catacolorext.COL_TIPO = 'EXTERIOR'
            AND vs.VEH_COLOEXTE = catacolorext.COL_CLAVE
        LEFT JOIN PNC_PARAMETR puertas
            ON cat.UNC_PTAS = puertas.PAR_IDENPARA
            AND puertas.PAR_TIPOPARA = 'PTA'
        LEFT JOIN PNC_PARAMETR cilindros
            ON cat.UNC_CILINDROS = cilindros.PAR_IDENPARA
            AND cilindros.PAR_TIPOPARA = 'CIL'
        LEFT JOIN PNC_PARAMETR aduana
            ON vs.VEH_ADUANA = aduana.PAR_IDENPARA
            AND aduana.PAR_TIPOPARA = 'ADNA'
        LEFT JOIN PNC_PARAMETR lineamodelo
            ON cat.UNC_FAMILIA = lineamodelo.PAR_IDENPARA
            AND lineamodelo.PAR_TIPOPARA = 'CLI'
        WHERE
            upn.PEN_IDPEDI = ?
            AND upn.PEN_IDCATALOGO = ?
            AND upn.PEN_MODELO = ?
    """


def build_address(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    address: Dict[str, Any] = {}
    mapping = {
        "street": "street",
        "number": "street_number",
        "int_number": "int_number",
        "neighborhood": "neighborhood",
        "city": "city",
        "postal_code": "postal_code",
        "country": "country",
    }
    for target, source in mapping.items():
        value = clean(row.get(source))
        if value:
            address[target] = value
    state = clean(row.get("state"))
    if state:
        address["state"] = STATE_MAP.get(state, state)
    if address and "country" not in address:
        address["country"] = "MX"
    return address or None


def build_phone(row: Dict[str, Any], number_key: str = "phone_number", country_key: str = "phone_country_code") -> Optional[Dict[str, str]]:
    number = clean(row.get(number_key))
    if not number:
        return None
    return {
        "number": number,
        "country_code": clean(row.get(country_key)) or "52",
    }


def build_name(row: Dict[str, Any], prefix: str = "") -> Optional[Dict[str, str]]:
    name = clean(row.get(f"{prefix}first_name"))
    paternal = clean(row.get(f"{prefix}paternal"))
    maternal = clean(row.get(f"{prefix}maternal"))
    result: Dict[str, str] = {}
    if name:
        result["name"] = name
    if paternal:
        result["paternal"] = paternal
    if maternal:
        result["maternal"] = maternal
    return result or None


def add_optional(payload: Dict[str, Any], key: str, value: Any) -> None:
    if value is not None and value != "":
        payload[key] = value


def parse_customer(row: Dict[str, Any], organization: str) -> Optional[Dict[str, Any]]:
    customer_id = clean(row.get("customer_id"))
    customer_type = (clean(row.get("customer_type")) or "").upper()
    if not customer_id or customer_type not in {"FIS", "FIE", "MOR"}:
        return None

    base: Dict[str, Any] = {
        "id": customer_id,
        "organization": organization,
        "metadata": {
            "source": "refran",
            "source_customer_type": customer_type,
        },
    }
    add_optional(base, "email", clean(row.get("email")))
    add_optional(base, "phone", build_phone(row))
    add_optional(base, "rfc", clean(row.get("rfc")))
    add_optional(base, "economical_activity", clean(row.get("economical_activity")))
    add_optional(base, "address", build_address(row))
    add_optional(base, "registration_date", parse_date_ymd(row.get("registration_date")))

    if customer_type in {"FIS", "FIE"}:
        base["name"] = build_name(row) or {"name": clean(row.get("denomination")) or "SIN NOMBRE"}
        add_optional(base, "curp", clean(row.get("curp")))
        add_optional(base, "birth_date", parse_date_ymd(row.get("birth_date")))
        return base

    denomination = clean(row.get("denomination")) or clean(row.get("first_name"))
    if not denomination:
        return None
    base["denomination"] = denomination
    add_optional(base, "moral_type", clean(row.get("moral_type")))
    add_optional(base, "constitution_date", parse_date_ymd(row.get("constitution_date")))

    contact_name = build_name(row, "contact_")
    if contact_name:
        contact: Dict[str, Any] = {"name": contact_name}
        add_optional(contact, "id", clean(row.get("contact_id")))
        add_optional(contact, "email", clean(row.get("contact_email")))
        add_optional(
            contact,
            "phone",
            build_phone(row, "contact_phone_number", "contact_phone_country_code"),
        )
        base["contact"] = contact

    representative_id = clean(row.get("representative_id"))
    representative_name = build_name(row, "representative_")
    if representative_id and representative_name:
        representative: Dict[str, Any] = {
            "id": representative_id,
            "customer_id": customer_id,
            "organization": organization,
            "name": representative_name,
        }
        add_optional(representative, "rfc", clean(row.get("representative_rfc")))
        add_optional(representative, "curp", clean(row.get("representative_curp")))
        add_optional(
            representative,
            "birth_date",
            parse_date_ymd(row.get("representative_birth_date")),
        )
        add_optional(
            representative,
            "registration_date",
            parse_date_ymd(row.get("representative_registration_date")),
        )
        base["representatives"] = [representative]
    return base


def parse_vehicle(row: Dict[str, Any], organization: str) -> Optional[Dict[str, Any]]:
    vin = clean(row.get("vin"))
    brand = clean(row.get("brand"))
    model = clean(row.get("model"))
    year = clean(row.get("year"))
    if not vin or vin.startswith("-") or not brand or not model or not year:
        return None

    vehicle: Dict[str, Any] = {
        "id": vin,
        "brand": brand,
        "model": model,
        "vin": vin,
        "year": year,
        "organization": organization,
    }
    for target in (
        "model_line",
        "color",
        "interior_color",
        "motor_origin",
        "origin",
        "inventory_number",
        "catalog_id",
        "capacity",
        "doors",
        "cylinders",
    ):
        add_optional(vehicle, target, clean(row.get(target)))
    line = clean(row.get("line"))
    add_optional(vehicle, "line", VEHICLE_LINE_MAP.get(line or "", line))
    add_optional(vehicle, "msrp", safe_money(row.get("msrp")))

    pediment = {
        "number": clean(row.get("pediment_number")),
        "date": clean(row.get("pediment_date")),
        "custom": clean(row.get("pediment_custom")),
    }
    pediment = {key: value for key, value in pediment.items() if value}
    if pediment:
        vehicle["pediment"] = pediment
    return vehicle


def parse_order(
    row: Dict[str, Any],
    customer: Dict[str, Any],
    vehicle: Dict[str, Any],
    organization: str,
    transaction_type: str,
) -> Optional[Dict[str, Any]]:
    order_id = clean(row.get("order_id"))
    customer_id = clean(customer.get("id"))
    vehicle_id = clean(vehicle.get("id"))
    if not order_id or not customer_id or not vehicle_id:
        return None

    source_seller_id = clean(row.get("seller_id"))
    seller_id = SELLER_ID_MAP.get(source_seller_id or "", "XXX") if source_seller_id else None
    seller_name = " ".join(
        part
        for part in (
            clean(row.get("seller_first_name")),
            clean(row.get("seller_paternal")),
            clean(row.get("seller_maternal")),
        )
        if part
    )
    order: Dict[str, Any] = {
        "id": order_id,
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "organization": organization,
        "transaction_type": transaction_type,
        "status": "pending",
        "metadata": {
            "source": "refran",
            "source_seller_id": source_seller_id,
            "seller_name": seller_name or None,
            "sub_order_source": clean(row.get("sub_order_source")),
            "source_serial": clean(row.get("serial")),
            "source_catalog_id": clean(row.get("catalog_id")),
            "source_catalog_model": clean(row.get("catalog_model")),
        },
    }
    order["metadata"] = {key: value for key, value in order["metadata"].items() if value}
    add_optional(order, "invoice_no", clean(row.get("invoice_no")))
    add_optional(order, "seller_id", seller_id)
    add_optional(order, "transaction_date", parse_date_ymd(row.get("transaction_date")))
    add_optional(order, "subtotal", safe_money(row.get("subtotal")))
    add_optional(order, "iva", safe_money(row.get("iva")))
    add_optional(order, "total", safe_money(row.get("total")))
    add_optional(order, "isan", safe_money(row.get("isan")))
    sub_order_type = SUB_ORDER_TYPE_MAP.get(clean(row.get("sub_order_source")) or "")
    add_optional(order, "sub_order_type", sub_order_type)
    return order


def organization_for_db(db_name: str, override: Optional[str]) -> str:
    return override or db_name


def fetch_targets(
    source: RefranSqlServerSource,
    db_names: Sequence[str],
    transaction_types: Sequence[str],
    from_date: Optional[str],
    to_date: Optional[str],
    cancelled: bool = False,
) -> List[TargetOrder]:
    targets: List[TargetOrder] = []
    seen: set[Tuple[str, str, str]] = set()
    for db_name in db_names:
        for transaction_type in transaction_types:
            query_builder = cancelled_scan_query if cancelled else active_scan_query
            query, params = query_builder(transaction_type, from_date, to_date)
            print(f"Fetching {transaction_type} {'cancelled' if cancelled else 'active'} targets from {db_name}")
            rows = source.fetch_rows(db_name, query, params)
            for row in rows:
                order_id = clean(row.get("order_id"))
                if not order_id:
                    continue
                key = (db_name, order_id, transaction_type)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(
                    TargetOrder(
                        db_name=db_name,
                        order_id=order_id,
                        transaction_type=transaction_type,
                        operation_date=parse_date_ymd(row.get("operation_date")),
                        source_customer_id=clean(row.get("source_customer_id")),
                        order_status=clean(row.get("order_status")),
                        invoice_status=clean(row.get("invoice_status")),
                    )
                )
    targets.sort(key=lambda target: target.operation_date or "", reverse=True)
    return targets


def build_refran_order_entities(
    source: RefranSqlServerSource,
    db_names: Sequence[str],
    transaction_types: Sequence[str],
    organization_override: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
    source_limit: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    targets = fetch_targets(source, db_names, transaction_types, from_date, to_date, cancelled=False)
    if source_limit is not None:
        targets = targets[:source_limit]

    vehicles: Dict[Tuple[str, str], Dict[str, Any]] = {}
    customers: Dict[Tuple[str, str], Dict[str, Any]] = {}
    orders: Dict[Tuple[str, str], Dict[str, Any]] = {}
    stats = defaultdict(int)
    stats["target_orders"] = len(targets)

    for target in targets:
        organization = organization_for_db(target.db_name, organization_override)
        customer_rows = source.fetch_rows(target.db_name, customer_query(), [target.order_id])
        if not customer_rows:
            stats["missing_customer_rows"] += 1
            continue
        customer = parse_customer(customer_rows[0], organization)
        if not customer:
            stats["invalid_customers"] += 1
            continue

        order_rows = source.fetch_rows(target.db_name, order_query(), [target.order_id])
        if not order_rows:
            stats["missing_order_rows"] += 1
            continue
        if len(order_rows) > 1:
            stats["multi_vehicle_order_rows"] += len(order_rows) - 1

        for order_row in order_rows:
            catalog_id = clean(order_row.get("catalog_id"))
            catalog_model = clean(order_row.get("catalog_model"))
            if not catalog_id or not catalog_model:
                stats["missing_vehicle_lookup_keys"] += 1
                continue
            vehicle_rows = source.fetch_rows(
                target.db_name,
                vehicle_query(),
                [target.order_id, catalog_id, catalog_model],
            )
            if not vehicle_rows:
                stats["missing_vehicle_rows"] += 1
                continue
            vehicle = parse_vehicle(vehicle_rows[0], organization)
            if not vehicle:
                stats["invalid_vehicles"] += 1
                continue
            order = parse_order(order_row, customer, vehicle, organization, target.transaction_type)
            if not order:
                stats["invalid_orders"] += 1
                continue

            customers[(customer["id"], organization)] = customer
            vehicles[(vehicle["id"], organization)] = vehicle
            order_key = (order["id"], organization)
            if order_key in orders:
                stats["duplicate_orders"] += 1
                continue
            orders[order_key] = order
            stats["prepared_orders"] += 1

    stats["prepared_customers"] = len(customers)
    stats["prepared_vehicles"] = len(vehicles)
    return list(vehicles.values()), list(customers.values()), list(orders.values()), dict(stats)


def build_refran_cancellation_targets(
    source: RefranSqlServerSource,
    db_names: Sequence[str],
    transaction_types: Sequence[str],
    organization_override: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
    source_limit: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    targets = fetch_targets(source, db_names, transaction_types, from_date, to_date, cancelled=True)
    if source_limit is not None:
        targets = targets[:source_limit]

    prepared: List[Dict[str, str]] = []
    seen: set[str] = set()
    stats = defaultdict(int)
    stats["source_targets"] = len(targets)

    for target in targets:
        organization = organization_for_db(target.db_name, organization_override)
        route_id = f"{target.order_id}|{target.order_id}~{organization}"
        if route_id in seen:
            stats["duplicate_targets"] += 1
            continue
        seen.add(route_id)
        prepared.append(
            {
                "route_id": route_id,
                "order_id": target.order_id,
                "organization": organization,
                "transaction_type": target.transaction_type,
                "operation_date": target.operation_date or "",
                "order_status": target.order_status or "",
                "invoice_status": target.invoice_status or "",
            }
        )
        stats["prepared"] += 1
    return prepared, dict(stats)


def progress_item_id(endpoint: str, item: Dict[str, Any]) -> str:
    item_id = clean(item.get("id")) or "<missing-id>"
    organization = clean(item.get("organization"))
    if item_id != "<missing-id>" and organization:
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


async def send_refran_entity_batches(
    api_base: str,
    token_manager: TokenManager,
    db_key: str,
    vehicles: Sequence[Dict[str, Any]],
    customers: Sequence[Dict[str, Any]],
    orders: Sequence[Dict[str, Any]],
    batch_size: int,
    verbose: bool = False,
) -> Dict[str, Dict[str, int]]:
    progress = JsonProgress(f"progress_refran_{db_key}_live.json", ("vehicles", "customers", "orders"))
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


async def cancel_refran_targets(
    api_base: str,
    token_manager: TokenManager,
    db_key: str,
    targets: Sequence[Dict[str, str]],
    batch_size: int,
    verbose: bool = False,
) -> Dict[str, int]:
    progress = JsonProgress(f"progress_refran_cancel_orders_{db_key}_live.json", ("cancelled",))
    token_manager.get_token()
    totals = {"cancelled": 0, "skipped": 0, "errors": 0}

    async with aiohttp.ClientSession() as session:
        total_batches = (len(targets) + batch_size - 1) // batch_size
        for start in range(0, len(targets), batch_size):
            batch = targets[start : start + batch_size]
            batch_num = (start // batch_size) + 1
            print(f"Sending cancel batch {batch_num}/{total_batches} to orders ({len(batch)} item(s))")
            for idx, target in enumerate(batch, start=1):
                route_id = target["route_id"]
                if progress.contains("cancelled", route_id):
                    print(f"  [orders-cancel] Item {idx} (route_id={route_id}): SKIPPED")
                    totals["skipped"] += 1
                    continue

                encoded_id = quote(route_id, safe="")
                url = f"{api_base.rstrip('/')}/orders/{encoded_id}/cancel"
                if verbose:
                    print(f"  [orders-cancel] Target {idx}: {json.dumps(target, indent=2)}")
                try:
                    async with session.post(url, headers=token_manager.headers(), json={}) as response:
                        text = await response.text()
                        try:
                            response_data = json.loads(text)
                        except Exception:
                            response_data = text
                        print(f"  [orders-cancel] Item {idx} (route_id={route_id}): {response.status} - {response_data}")
                        if 200 <= response.status < 300:
                            progress.add("cancelled", route_id)
                            totals["cancelled"] += 1
                        else:
                            totals["errors"] += 1
                except Exception as exc:
                    print(f"  [orders-cancel] Error on item {idx} (route_id={route_id}): {exc}")
                    totals["errors"] += 1
            await asyncio.sleep(BATCH_DELAY_SECONDS)
    return totals


def effective_from_date(args: Any) -> Optional[str]:
    if args.all_history:
        return args.from_date
    return args.from_date or default_from_date()


__all__ = [
    "RefranSqlServerSource",
    "TokenManager",
    "add_refran_api_args",
    "add_refran_source_args",
    "build_refran_cancellation_targets",
    "build_refran_order_entities",
    "cancel_refran_targets",
    "effective_from_date",
    "parse_db_names",
    "parse_transaction_types",
    "require_auth_args",
    "require_source_args",
    "send_refran_entity_batches",
]
