# GMUNI Connector Handoff

## Source And Runtime

GMUNI reads Oracle data through `python-oracledb` thick mode. All GMUNI scripts
share the same DB map shape: each `DATABASES` entry has a DB name, host, group,
and sometimes `no_route` plus `direct_tunnel_port`.

Default Oracle user is `PRESA`. The password is supplied with `--password` or,
for `test_oracle_connection.py`, `ORACLE_PASSWORD`.

GMUNI API auth is currently hardcoded in each script as:

- `API_BASE = "https://api.presa.anjer.mx"`
- `AUTH_CONFIG["tenant_id"] = "carone"`
- `AUTH_CONFIG["client_id"] = "carone"`
- `AUTH_CONFIG["client_secret"]` in the script

Each run logs in with `POST /auth/login`, then sends `Authorization: <token>` and
`Content-Type: application/json`.

## Script Matrix

| Script | Source | Receiver endpoint | Progress file |
| --- | --- | --- | --- |
| `fetch_and_send_gmuni.py` | `autos.VT_VFACTURAS_PLD_CARONE` | `POST /vehicles`, `POST /customers`, `POST /orders` | `progress_{DB}_live.json` |
| `fetch_and_send_gmuni_payments.py` | `autos.CC_VRECIBOS_SECU_PLD_CARONE` | `POST /payments` | `progress_payments_{DB}_live.json` |
| `fetch_and_send_gmuni_payments_enre_status.py` | same payment view | `POST /payments` | `progress_payments_{DB}_live.json` |
| `fetch_and_send_gmuni_seller_names.py` | `autos.VT_VENDEDORES`, `VT_VENDEDORES`, or invoice fallback | `POST /seller-accounts/{seller_id}/add-name` by default | `progress_seller_names_{run_name}_live.json` |
| `fetch_and_cancel_gmuni_orders.py` | `autos.VT_VFACTURAS_PLD_CARONE` | `POST /orders/{route_id}/cancel` | `progress_cancel_orders_{DB}_live.json` |
| `fetch_and_cancel_gmuni_payments.py` | `autos.CC_VRECIBOS_SECU_PLD_CARONE` | `POST /payments/{route_id}/cancel` | `progress_cancel_payments_{DB}_live.json` |

Both order and payment readers default `from_date` to May 1 of the current
reporting year when `--from-date` is not supplied. Order scripts filter on
`FAAU_FECHA`; payment scripts filter on `SECU_FECHAEMISION`.

## Vehicle Payload

Built by `parse_vehicle()` in `fetch_and_send_gmuni.py`, then sent to
`POST /vehicles`.

```json
{
  "id": "VIN",
  "brand": "MARC_DESCRIP",
  "model": "MODE_DESCRIPCION",
  "vin": "VIN",
  "year": "FAAU_VEHI_ANIO",
  "inventory_number": "FAAU_VEHI_NUMEROINVENTARIO"
}
```

Only `vin`, `brand`, `model`, and `year` are receiver-side required fields. The
script does not currently set `organization` on GMUNI vehicle payloads.

## Customer Payload

Built by `parse_customer()` in `fetch_and_send_gmuni.py`, then sent to
`POST /customers`.

Physical customer example:

```json
{
  "id": "FAAU_CLIE_CLAVE",
  "organization": "EMPR_NOMBRE--EMPR_EMPRESAID--AGEN_IDAGENCIA",
  "address": {
    "street": "FAAU_DOMICILIOFACTURA",
    "number": "FAAU_NUMEXT",
    "int_number": "FAAU_NUMINT",
    "neighborhood": "FAAU_COLONIA",
    "city": "MUNI_NOMBRE",
    "state": "EDOS_NOMBRE",
    "postal_code": "FAAU_CP",
    "country": "MX"
  },
  "phone": {
    "country_code": "52",
    "number": "CLIE_TELEFONO1"
  },
  "email": "CLIE_EMAIL",
  "rfc": "FAAU_RFCFACTURA",
  "name": {
    "name": "CLIE_NOMBRE",
    "paternal": "CLIE_APELLIDOPATERNO",
    "maternal": "CLIE_APELLIDOMATERNO"
  },
  "curp": "CLIE_CURP",
  "economical_activity": "CVE_ACTI_ECON_PF"
}
```

Moral customer example:

```json
{
  "id": "FAAU_CLIE_CLAVE",
  "organization": "EMPR_NOMBRE--EMPR_EMPRESAID--AGEN_IDAGENCIA",
  "denomination": "CLIE_RAZONSOCIAL or FAAU_RAZONFACTURA",
  "rfc": "FAAU_RFCFACTURA",
  "economical_activity": "CVE_ACTI_ECON_PM",
  "representatives": [
    {
      "id": "FAAU_CLIE_CLAVE-REP1",
      "name": {
        "name": "CLIE_NOMBREREPLEGAL",
        "paternal": "CLIE_APELLIDOPATERNOREPLEG",
        "maternal": "CLIE_APELLIDOMATERNOREPLEG"
      },
      "birth_date": "CLIE_FECHANACIMIENTOREPLEG",
      "rfc": "CLIE_RFCREPLEGAL",
      "curp": "CLIE_CURPREPLEGAL"
    }
  ]
}
```

The script skips generic RFC `XAXX010101000` when filling `rfc`.

## Order Payload

Built by `parse_order()` in `fetch_and_send_gmuni.py`, then sent to
`POST /orders`.

```json
{
  "id": "FAAU_NOFACTURA",
  "customer_id": "FAAU_CLIE_CLAVE",
  "vehicle_id": "VEHI_SERIE",
  "invoice_no": "FAAU_NOFACTURA",
  "organization": "EMPR_NOMBRE--EMPR_EMPRESAID--AGEN_IDAGENCIA",
  "invoice_date": "FAAU_FECHA as ISO datetime",
  "transaction_date": "FECHAMOV date or invoice date",
  "subtotal": "FAAU_TOTAL - FAAU_IVA - FAAU_ISAN",
  "iva": "FAAU_IVA",
  "isan": "FAAU_ISAN",
  "total": "FAAU_TOTAL",
  "seller_id": "FAAU_VEND_CLAVE",
  "transaction_type": "mapped from FORM_CARTERA / FAAU_FORM_TIPOVENTA",
  "sub_order_type": "mapped from FORM_GRUPODEVENTADIR / FAAU_FORM_TIPOVENTA",
  "status": "pending",
  "reference": "PRIM_FOLIO",
  "vendor_rfc": "CLAVE_SUJETO_OBLIGADO",
  "dealership": "AGEN_AGENCIA",
  "metadata": {
    "cfdi_uuid": "PRIM_UUIDS",
    "form_tipoventa": "FAAU_FORM_TIPOVENTA",
    "form_descripcion": "FORM_DESCRIPCION",
    "dms": "DMS",
    "period": "PERIODO",
    "seller_name": "VEND_NOMBRE",
    "branch": "AGEN_NOMBRE_SUCURSAL"
  }
}
```

`fetch_and_send_gmuni.py` sends vehicles first, customers second, and orders
last. If an order fails because a dependency is missing, it attempts to re-post
the referenced customer and vehicle before retrying the order.

## Payment Payload

Built by `build_payment_payload()` in `fetch_and_send_gmuni_payments.py` and
`fetch_and_send_gmuni_payments_enre_status.py`, then sent to `POST /payments`.

```json
{
  "id": "SECU_REGLON",
  "salt": "SECU_REGLON",
  "order_id": "PRIM_DOCUMENTO|PRIM_DOCUMENTO",
  "organization": "EMPR_NOMBRE--EMPR_EMPRESAID--AGEN_IDAGENCIA",
  "payment_form": "SAT payment form code",
  "payment_type": "internal",
  "cfdi_conceptual_type": "payment_receipt or credit_note",
  "amount": "negative SECU_IMPORTE",
  "total": "negative SECU_IMPORTE",
  "date": "SECU_FECHAEMISION or ENRE_FECHA as ISO datetime",
  "operation_reference": "ENRE_CONCEPTO or SECU_REFERENCIA1/2/3"
}
```

Payment selection rules:

- `ENRE_STATUS` is sendable when empty, `AC`, or starts with `NO ENCONTR` /
  `NOT ENCONTR`.
- Rows with cancellation markers are skipped unless `ORIGEN` is `07 NCRE` or
  `20 OTROS`.
- `ORIGEN = 20 OTROS` forces `pld_payment_form = "0"` and
  `pld_monetary_instrument = "0"`.
- `cfdi_conceptual_type` is `credit_note` when `payment_form == "30"`;
  otherwise it is `payment_receipt`.
- `payment_form` is resolved in this order: `FPAG_FORMAXML`,
  `ENRE_FPAG_CLAVE` / `CVE_FORMAPAGO` mapping, `CVE_INST_MONETARIO`,
  instrument/form descriptions, then fallback `"99"`.

## Cancellation Routes

Order cancellations use active status from `FAAU_STATUS`. Only non-`AC` rows are
sent.

```text
route_id = "{FAAU_NOFACTURA}|{FAAU_NOFACTURA}~{organization}"
POST /orders/{urlencoded route_id}/cancel
body: {}
```

Payment cancellations use active status from `ENRE_STATUS`. Only non-`AC` rows
are sent.

```text
route_id = "{SECU_REGLON}|{SECU_REGLON}~{organization}"
POST /payments/{urlencoded route_id}/cancel
body: {}
```

The receiver expands these into Dynamo node keys like
`order~{id}|{salt}~{organization}` or `payment~{id}|{salt}~{organization}`.

## Seller Account Names

`fetch_and_send_gmuni_seller_names.py` sends seller display names to:

```text
POST /seller-accounts/{urlencoded seller_id}/add-name
```

Default payload:

```json
{
  "name": {
    "name": "NOMBRE",
    "paternal": "APELLIDOPATERNO",
    "maternal": "APELLIDOMATERNO"
  }
}
```

The script can use `--method POST|PATCH|PUT` and
`--endpoint-suffix <suffix>`.
