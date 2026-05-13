# Universidad Connector Handoff

## Source And Runtime

Universidad reads a flattened sales/payments source. The source can be:

- an `.xlsx` workbook via `--xlsx` or `UNIVERSIDAD_XLSX`;
- a SQL Server table/view through ODBC via `--connection-string` /
  `UNIVERSIDAD_ODBC_CONNECTION_STRING` plus `--table`; or
- a custom SQL query via `--query`, `--query-file`, or
  `UNIVERSIDAD_SOURCE_QUERY`.

The source rows are expected to expose the same columns as
`VENTAS UNIVERSIDAD.xlsx`.

API auth is not hardcoded. Supply:

```bash
export PRESA_API_BASE=https://api.presa.anjer.mx
export PRESA_TENANT_ID=<tenant>
export PRESA_CLIENT_ID=<client>
export PRESA_CLIENT_SECRET=<secret>
```

or pass the equivalent CLI args. Each script logs in with `POST /auth/login`,
then sends `Authorization: <token>` and `Content-Type: application/json`.

Organization defaults to `SUCURSAL--CpnyID`. You can override with
`--organization`, or use `--organization-mode sucursal` when only `SUCURSAL`
should be used.

## Script Matrix

| Script | Source date field | Receiver endpoint | Progress file |
| --- | --- | --- | --- |
| `fetch_and_send_universidad.py` | `FechaFact` | `POST /vehicles`, `POST /customers`, `POST /orders` | `progress_universidad_{db_key}_live.json` |
| `fetch_and_send_universidad_payments.py` | `fechaTimbrePago` | `POST /payments` | `progress_universidad_payments_{db_key}_live.json` |
| `fetch_and_cancel_universidad_orders.py` | `fechacanc` | `POST /orders/{route_id}/cancel` | `progress_universidad_cancel_orders_{db_key}_live.json` |
| `fetch_and_cancel_universidad_payments.py` | `fechacanc` | `POST /payments/{route_id}/cancel` | `progress_universidad_cancel_payments_{db_key}_live.json` |

The default `db_key` is `universidad`, but copied progress files show historical
runs with keys like `mxa_first_row_lafe` and `mxa_full_sucursal`.

## Source Filters

All Universidad scripts share source filters from `add_source_args()`:

- `--from-date` and `--to-date` filter by the script's default date field unless
  `--date-field` is supplied.
- `--sucursal` filters exact trimmed `SUCURSAL`.
- `--cpny-id` filters exact trimmed `CpnyID`.
- `--source-limit` limits SQL rows before transformation.
- `--limit` limits payloads/targets after transformation.
- `--dry-run` prints sample payloads and skips API calls.

Rows with `Cancelacion` or `fechacanc` are treated as cancelled. Send scripts
skip those rows unless `--include-cancelled` is supplied. Cancel scripts only
use cancelled rows.

## Vehicle Payload

Built by `parse_vehicle()` in `universidad_common.py`, then sent to
`POST /vehicles`.

```json
{
  "id": "NoSerie",
  "brand": "Marca",
  "model": "Linea or Catalogo",
  "vin": "NoSerie",
  "year": "Modelo or inferred from VIN",
  "organization": "SUCURSAL--CpnyID",
  "line": "Linea",
  "catalog_id": "Catalogo",
  "color": "Colorext",
  "interior_color": "Colorint",
  "doors": "Puertas",
  "cylinders": "Cilindros"
}
```

Rows missing `NoSerie`, `Marca`, `model`, or `year` are counted as missing
vehicles.

## Customer Payload

Built by `parse_customer()` in `universidad_common.py`, then sent to
`POST /customers`.

Customer ID is:

- uppercase `Rfc`, unless it is generic `XAXX010101000` or `XEXX010101000`;
- otherwise `RFC-NAME-SLUG` when an RFC exists;
- otherwise `CUSTOMER-NAME-SLUG`.

Physical customer example:

```json
{
  "id": "resolved customer id",
  "organization": "SUCURSAL--CpnyID",
  "metadata": {
    "source": "VENTAS UNIVERSIDAD",
    "cpny_id": "CpnyID",
    "sucursal": "SUCURSAL",
    "customer_type": "Tipo Cliente"
  },
  "email": "EMailAddr",
  "phone": {
    "country_code": "52",
    "number": "Tel1 or Tel2"
  },
  "address": {
    "street": "Direcc",
    "neighborhood": "Direcc2",
    "city": "Ciudad",
    "state": "Estado",
    "postal_code": "CP",
    "country": "Pais or MX"
  },
  "rfc": "Rfc",
  "name": {
    "name": "Nombre or Cliente",
    "paternal": "Paterno",
    "maternal": "Materno"
  },
  "curp": "curp"
}
```

Moral customer example:

```json
{
  "id": "resolved customer id",
  "organization": "SUCURSAL--CpnyID",
  "metadata": {
    "source": "VENTAS UNIVERSIDAD",
    "cpny_id": "CpnyID",
    "sucursal": "SUCURSAL",
    "customer_type": "Tipo Cliente"
  },
  "denomination": "Cliente or Nombre",
  "email": "EMailAddr",
  "phone": {
    "country_code": "52",
    "number": "Tel1 or Tel2"
  },
  "address": {
    "street": "Direcc",
    "neighborhood": "Direcc2",
    "city": "Ciudad",
    "state": "Estado",
    "postal_code": "CP",
    "country": "Pais or MX"
  },
  "rfc": "Rfc"
}
```

The connector treats a row as moral when `Tipo Cliente` contains `MORAL` or
`DISTRIB`.

## Order Payload

Built by `parse_order()` in `universidad_common.py`, then sent to
`POST /orders`.

```json
{
  "id": "Factura",
  "customer_id": "resolved customer id",
  "vehicle_id": "NoSerie",
  "invoice_no": "Factura",
  "organization": "SUCURSAL--CpnyID",
  "reference": "Pedido",
  "transaction_type": "retail, pre_owned, or exchange",
  "sub_order_type": "out_right, bank, or exchange",
  "status": "pending",
  "metadata": {
    "source": "VENTAS UNIVERSIDAD",
    "cfdi_uuid": "uuidventa",
    "cpny_id": "CpnyID",
    "sucursal": "SUCURSAL",
    "tipo_vta": "TipoVta",
    "seller_name": "Vendedor",
    "seller_id": "NoVendedor"
  },
  "invoice_date": "FechaFact as ISO datetime",
  "transaction_date": "FechaFact date",
  "subtotal": "subtotal",
  "iva": "iva",
  "isan": "Isan",
  "total": "Total",
  "seller_id": "NoVendedor"
}
```

`transaction_type` is `exchange` when `TipoVta` contains `INTER`, `pre_owned`
when `TipoVta` contains `USAD` or `Marca == USADO`, otherwise `retail`.

`sub_order_type` is `exchange` when `TipoVta` contains `INTER`, `bank` when it
contains `CRED`, otherwise `out_right`.

## Payment Payload

Built by `parse_payment()` in `universidad_common.py`, then sent to
`POST /payments`.

Payment ID is:

- `uuidPago-Factura` when both exist;
- otherwise `serie-folio-Factura` when all three exist.

```json
{
  "id": "resolved payment id",
  "salt": "resolved payment id",
  "order_id": "Factura|Factura",
  "organization": "SUCURSAL--CpnyID",
  "payment_form": "MetodoDePago normalized to SAT two-digit code",
  "payment_type": "internal",
  "cfdi_conceptual_type": "payment_receipt",
  "amount": "pago",
  "total": "pago",
  "invoice_id": "Factura",
  "invoice_uuid": "uuidventa",
  "series": "serie",
  "folio": "folio",
  "uuid": "uuidPago",
  "payment_uuid": "uuidPago",
  "rfc": "Rfc",
  "customer_id": "resolved customer id",
  "vehicle_id": "NoSerie",
  "date": "fechaTimbrePago as ISO datetime",
  "operation_reference": "serie-folio"
}
```

`payment_form` falls back to `"99"` when `MetodoDePago` cannot be normalized.
Universidad does not currently set `pld_payment_form` or
`pld_monetary_instrument`.

## Cancellation Routes

Cancelled order rows use:

```text
route_id = "{Factura}|{Factura}~{organization}"
POST /orders/{urlencoded route_id}/cancel
body: {}
```

Target metadata kept only for logging/progress:

```json
{
  "route_id": "Factura|Factura~SUCURSAL--CpnyID",
  "order_id": "Factura",
  "cancel_date": "fechacanc as YYYY-MM-DD",
  "reason": "Cancelacion or cancelled"
}
```

Cancelled payment rows use:

```text
route_id = "{payment_id}|{payment_id}~{organization}"
POST /payments/{urlencoded route_id}/cancel
body: {}
```

Target metadata kept only for logging/progress:

```json
{
  "route_id": "payment_id|payment_id~SUCURSAL--CpnyID",
  "payment_id": "resolved payment id",
  "order_id": "Factura",
  "cancel_date": "fechacanc as YYYY-MM-DD",
  "reason": "Cancelacion or cancelled"
}
```
