# Lambda Endpoint Explainer

This is the receiver-side contract used by the copied connector scripts.

## Authentication

All connector API calls first use:

```text
POST /auth/login
headers:
  tenant_id: <tenant>
  tenant: <tenant>
body:
  {
    "client_id": "<client id>",
    "client_secret": "<client secret>"
  }
```

The response token is sent as:

```text
Authorization: <token>
Content-Type: application/json
```

The receiving lambdas require an admin principal for all POST/cancel paths used
by these scripts.

## Body Shape

The create endpoints accept either a single object or an array of objects:

```json
{ "id": "one-item" }
```

or:

```json
[
  { "id": "first-item" },
  { "id": "second-item" }
]
```

The current connector scripts send one object at a time, even though the Lambda
payload enums support multiple records.

## Vehicles Lambda

Routes in `lambdas/vehiclesv2/src/main.rs`:

```text
GET  /vehicles
POST /vehicles
POST /vehicles/{vehicle_id}
```

The connectors use only `POST /vehicles`.

Payload is parsed as `SinglePostVehicleRequestPayload`. Required receiver-side
fields are `brand`, `model`, `vin`, and `year`.

Relevant fields:

```json
{
  "brand": "required",
  "model": "required",
  "vin": "required",
  "year": "required",
  "model_line": "optional",
  "line": "optional",
  "color": "optional",
  "interior_color": "optional",
  "motor_origin": "optional",
  "origin": "optional",
  "organization": "optional",
  "inventory_number": "optional",
  "catalog_id": "optional",
  "armor_level": "optional",
  "capacity": "optional",
  "doors": "optional",
  "cylinders": "optional"
}
```

When `POST /vehicles/{vehicle_id}` is used, the handler can override the
vehicle salt with the path ID. The current connectors do not use this route.

## Customers Lambda

Routes in `lambdas/customersv2/src/main.rs`:

```text
GET   /customers
GET   /customers/{customer_id}
GET   /customers/{customer_id}/representatives
PATCH /customers/{customer_id}
PUT   /customers/{customer_id}
PATCH /customers/{customer_id}/fill-missing
PUT   /customers/{customer_id}/fill-missing
POST  /customers
POST  /customers/{customer_id}
POST  /customers/{customer_id}/representive
POST  /customers/{customer_id}/controlling-beneficiary
```

The connectors use only `POST /customers`.

The body is parsed as an untagged physical or moral customer:

Physical shape:

```json
{
  "id": "optional but supplied by connectors",
  "name": {
    "name": "required for physical",
    "paternal": "optional",
    "maternal": "optional"
  },
  "email": "optional",
  "phone": {
    "country_code": "52",
    "number": "optional"
  },
  "rfc": "optional",
  "curp": "optional",
  "birth_date": "optional",
  "metadata": {},
  "organization": "optional but supplied by connectors",
  "economical_activity": "optional",
  "address": {
    "street": "optional",
    "number": "optional",
    "int_number": "optional",
    "neighborhood": "optional",
    "city": "optional",
    "state": "optional",
    "postal_code": "optional",
    "country": "MX"
  }
}
```

Moral shape:

```json
{
  "id": "optional but supplied by connectors",
  "denomination": "required for moral",
  "email": "optional",
  "phone": {
    "country_code": "52",
    "number": "optional"
  },
  "rfc": "optional",
  "moral_type": "optional",
  "address": {},
  "economical_activity": "optional",
  "metadata": {},
  "organization": "optional but supplied by connectors",
  "representative": {},
  "representatives": []
}
```

GMUNI can send `representatives` embedded in a moral customer. Universidad does
not currently populate representatives.

## Orders Lambda

Routes in `lambdas/ordersv2/src/main.rs` include:

```text
GET   /orders
GET   /orders/{order_id}
POST  /orders
POST  /orders/{order_id}
POST  /orders/{order_id}/cancel
PATCH /orders/{order_id}
PUT   /orders/{order_id}
PATCH /orders/{order_id}/fill-missing
PUT   /orders/{order_id}/fill-missing
```

The connectors use `POST /orders` and `POST /orders/{route_id}/cancel`.

Create payload is parsed as `SingleOrderRequestPayload`.

```json
{
  "id": "optional but supplied by connectors",
  "customer_id": "required when customer object is not embedded",
  "vehicle_id": "required when vehicle object is not embedded",
  "invoice_no": "optional but supplied by connectors",
  "organization": "required by current order processing",
  "reference": "optional",
  "transaction_type": "retail, pre_owned, or exchange",
  "sub_order_type": "fleet, bank, out_right, exchange, etc.",
  "transaction_date": "YYYY-MM-DD",
  "invoice_date": "ISO datetime",
  "isan": 0,
  "iva": 0,
  "subtotal": 0,
  "total": 0,
  "vendor_rfc": "optional",
  "dealership": "optional",
  "status": "pending or other valid order status",
  "seller_id": "optional",
  "metadata": {}
}
```

The order handler validates that either `customer_id` or an embedded `customer`
exists, and either `vehicle_id` or an embedded `vehicle` exists. The current
connectors use IDs and send the dependency records separately before orders.

Cancel route format:

```text
POST /orders/{urlencoded route_id}/cancel
body: {}
```

The connector route ID should include organization to avoid cross-organization
fallbacks:

```text
{order_id}|{order_id}~{organization}
```

The Lambda decodes it and resolves the Dynamo node key as:

```text
order~{order_id}|{order_id}~{organization}
```

## Payments Lambda

Routes in `lambdas/paymentsv2/src/main.rs`:

```text
GET   /payments
GET   /payments/zip
GET   /payments/{payment_id}
POST  /payments
POST  /payments/{payment_id}
POST  /payments/{payment_id}/cancel
PATCH /payments/{payment_id}/fill-missing
PUT   /payments/{payment_id}/fill-missing
```

The connectors use `POST /payments` and `POST /payments/{route_id}/cancel`.

Create payload is parsed as `SinglePaymentRequestPayload`.

```json
{
  "id": "optional but supplied by connectors",
  "salt": "optional but supplied by connectors",
  "date": "ISO datetime string",
  "uuid": "optional CFDI/payment UUID",
  "payment_uuid": "optional payment UUID",
  "invoice_id": "optional invoice id",
  "invoice_uuid": "optional invoice UUID",
  "series": "optional",
  "folio": "optional",
  "organization": "optional but supplied by connectors",
  "payment_form": "SAT payment method/form code, usually two digits",
  "pld_payment_form": "optional PLD payment form",
  "pld_monetary_instrument": "optional PLD monetary instrument",
  "payment_type": "internal",
  "cfdi_conceptual_type": "payment_receipt or credit_note",
  "amount": 0,
  "total": 0,
  "operation_reference": "optional",
  "order_id": "order id route shape, usually Factura|Factura",
  "vehicle_id": "optional",
  "customer_id": "optional",
  "rfc": "optional"
}
```

Where to put the payment form:

- `payment_form` is the main SAT payment method/form used by the payment
  receiver.
- `pld_payment_form` and `pld_monetary_instrument` are separate optional PLD
  fields. GMUNI sets both to `"0"` for `ORIGEN = 20 OTROS`.
- `cfdi_conceptual_type` controls receipt classification. GMUNI sends
  `credit_note` for SAT form `30`; otherwise connectors send `payment_receipt`.

Cancel route format:

```text
POST /payments/{urlencoded route_id}/cancel
body: {}
```

The connector route ID should include organization:

```text
{payment_id}|{payment_id}~{organization}
```

The Lambda decodes it and resolves the Dynamo node key as:

```text
payment~{payment_id}|{payment_id}~{organization}
```

If the direct node lookup misses, the payment Lambda also tries UUID and ID
lookup candidates derived from the supplied path ID.

## Connector Endpoint Matrix

| Connector action | Method and path | Body |
| --- | --- | --- |
| Create vehicle | `POST /vehicles` | vehicle JSON object |
| Create customer | `POST /customers` | customer JSON object |
| Create order | `POST /orders` | order JSON object |
| Create payment | `POST /payments` | payment JSON object |
| Cancel order | `POST /orders/{urlencoded route_id}/cancel` | `{}` |
| Cancel payment | `POST /payments/{urlencoded route_id}/cancel` | `{}` |
| GMUNI seller name | `POST /seller-accounts/{seller_id}/add-name` | `{ "name": { ... } }` |
