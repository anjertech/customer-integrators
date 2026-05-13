# Customer Integrators

Standalone customer/order/payment connector scripts extracted from `presa/core`.

This repo currently contains the GMUNI and Universidad import/cancellation scripts plus
their direct helper modules and current progress trackers. Refran scripts were
intentionally left out for now.

## Contents

### GMUNI

- `fetch_and_send_gmuni.py` - Oracle orders feed to `vehicles`, `customers`, and `orders`.
- `fetch_and_send_gmuni_payments.py` - Oracle receipts feed to `payments`.
- `fetch_and_send_gmuni_payments_enre_status.py` - compatibility variant of the payments sender.
- `fetch_and_send_gmuni_seller_names.py` - seller account name updater.
- `fetch_and_cancel_gmuni_orders.py` - non-AC Oracle orders to `orders/{id}/cancel`.
- `fetch_and_cancel_gmuni_payments.py` - non-AC Oracle payments to `payments/{id}/cancel`.
- `gmuni_mappings.py` - transaction, sub-order, status, and organization mapping helpers.
- `oracle_client.py` and `test_oracle_connection.py` - Oracle thick-mode setup and tunnel checks.

### Universidad

- `fetch_and_send_universidad.py` - flattened sales rows to `vehicles`, `customers`, and `orders`.
- `fetch_and_send_universidad_payments.py` - flattened payment rows to `payments`.
- `fetch_and_cancel_universidad_orders.py` - cancelled rows to `orders/{id}/cancel`.
- `fetch_and_cancel_universidad_payments.py` - cancelled rows to `payments/{id}/cancel`.
- `universidad_common.py` - shared XLSX/ODBC loading, payload building, auth, progress, and send helpers.

### Progress Trackers

The progress JSON files live at repo root because the scripts read and write them
relative to the current working directory. Existing trackers copied here include:

- `progress_P_*_live.json` and older `progress_P_*.json` for GMUNI order/entity sends.
- `progress_payments_P_*_live.json` and older `progress_payments_P_*.json` for GMUNI payment sends.
- `progress_cancel_orders_P_*_live.json` for GMUNI order cancellations.
- `progress_cancel_payments_P_*_live.json` for GMUNI payment cancellations.
- `progress_seller_names_P_*_live.json` for GMUNI seller name updates.
- `progress_universidad_*_live.json` for Universidad order/entity sends and payment sends.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

GMUNI requires Oracle thick mode. Set one of:

```bash
export PRESA_ORACLE_CLIENT_DIR=/absolute/path/to/instantclient_23_3
export ORACLE_CLIENT_DIR=/absolute/path/to/instantclient_23_3
```

or place Instant Client under one of the relative paths accepted by
`oracle_client.py`, such as `./instantclient_23_3` or
`./vendor/oracle/instantclient_23_3`.

GMUNI also expects the SSH tunnel documented in the GMUNI scripts:

```bash
ssh -o PubkeyAuthentication=no -N \
  -L 16223:192.168.10.88:6223 \
  -L 16224:192.168.11.160:1521 \
  -L 16225:192.168.11.173:1521 \
  -L 16226:192.168.10.85:1521 \
  PRESA@192.168.10.83
```

## Handoff Docs

- [GMUNI connector handoff](docs/gmuni.md)
- [Universidad connector handoff](docs/universidad.md)
- [Lambda endpoint explainer](docs/lambda-endpoints.md)
