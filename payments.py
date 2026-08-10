"""Stripe and PayPal integration over the stdlib, plus a demo mode.

No SDKs, so there is nothing to install and nothing to keep patched. When no
keys are present the funnel runs in demo mode: an order is created, a simulated
gateway page is shown, and every downstream step behaves exactly as it will in
production. That makes the whole system testable before a gateway account exists.
"""
import json
import urllib.parse
import urllib.request
import urllib.error

import config


class PaymentError(Exception):
    pass


def _post(url, data, headers, as_json=False):
    body = json.dumps(data).encode() if as_json else urllib.parse.urlencode(data, doseq=True).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:500]
        raise PaymentError("%s returned %s: %s" % (url, exc.code, detail)) from exc
    except Exception as exc:                       # noqa: BLE001
        raise PaymentError(str(exc)) from exc


# --- Stripe ----------------------------------------------------------------
def stripe_checkout(order_ref, token, amount_gbp, product_name, email=None):
    data = {
        "mode": "payment",
        "success_url": "%s/order/%s?paid=1" % (config.PUBLIC_BASE_URL, token),
        "cancel_url": "%s/audit?cancelled=1" % config.PUBLIC_BASE_URL,
        "client_reference_id": order_ref,
        "metadata[order_token]": token,
        "metadata[order_ref]": order_ref,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "gbp",
        "line_items[0][price_data][unit_amount]": str(int(round(amount_gbp * 100))),
        "line_items[0][price_data][product_data][name]": product_name,
    }
    if email:
        data["customer_email"] = email
    out = _post("https://api.stripe.com/v1/checkout/sessions", data,
                {"Authorization": "Bearer %s" % config.STRIPE_SECRET_KEY,
                 "Content-Type": "application/x-www-form-urlencoded"})
    return out["id"], out["url"]


# --- PayPal ----------------------------------------------------------------
def _paypal_base():
    return "https://api-m.paypal.com" if config.PAYPAL_LIVE else "https://api-m.sandbox.paypal.com"


def _paypal_token():
    import base64
    creds = base64.b64encode(
        ("%s:%s" % (config.PAYPAL_CLIENT_ID, config.PAYPAL_SECRET)).encode()).decode()
    out = _post(_paypal_base() + "/v1/oauth2/token", {"grant_type": "client_credentials"},
                {"Authorization": "Basic %s" % creds,
                 "Content-Type": "application/x-www-form-urlencoded"})
    return out["access_token"]


def paypal_checkout(order_ref, token, amount_gbp, product_name):
    access = _paypal_token()
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": order_ref,
            "description": product_name[:127],
            "custom_id": token,
            "amount": {"currency_code": "GBP", "value": "%.2f" % amount_gbp},
        }],
        "application_context": {
            "brand_name": config.BRAND_NAME,
            "user_action": "PAY_NOW",
            "return_url": "%s/paypal/capture?token_ref=%s" % (config.PUBLIC_BASE_URL, token),
            "cancel_url": "%s/audit?cancelled=1" % config.PUBLIC_BASE_URL,
        },
    }
    out = _post(_paypal_base() + "/v2/checkout/orders", payload,
                {"Authorization": "Bearer %s" % access,
                 "Content-Type": "application/json"}, as_json=True)
    approve = next((l["href"] for l in out.get("links", []) if l.get("rel") == "approve"), None)
    if not approve:
        raise PaymentError("PayPal did not return an approval link")
    return out["id"], approve


def paypal_capture(paypal_order_id):
    access = _paypal_token()
    out = _post(_paypal_base() + "/v2/checkout/orders/%s/capture" % paypal_order_id, {},
                {"Authorization": "Bearer %s" % access,
                 "Content-Type": "application/json"}, as_json=True)
    return out.get("status") == "COMPLETED"


# --- Routing ---------------------------------------------------------------
def available():
    out = []
    if config.STRIPE_SECRET_KEY:
        out.append("stripe")
    if config.PAYPAL_CLIENT_ID and config.PAYPAL_SECRET:
        out.append("paypal")
    return out or ["demo"]


def start(provider, order_ref, token, amount_gbp, product_name, email=None):
    """Returns (provider_used, provider_ref, redirect_url)."""
    if provider == "stripe" and config.STRIPE_SECRET_KEY:
        sid, url = stripe_checkout(order_ref, token, amount_gbp, product_name, email)
        return "stripe", sid, url
    if provider == "paypal" and config.PAYPAL_CLIENT_ID:
        pid, url = paypal_checkout(order_ref, token, amount_gbp, product_name)
        return "paypal", pid, url

    # Once a real gateway is configured the demo step must never be reachable,
    # or anyone posting provider=demo walks off with a paid order for nothing.
    # Fall forward to a real gateway rather than back to the simulator.
    if config.PAYMENTS_LIVE:
        if config.STRIPE_SECRET_KEY:
            sid, url = stripe_checkout(order_ref, token, amount_gbp, product_name, email)
            return "stripe", sid, url
        pid, url = paypal_checkout(order_ref, token, amount_gbp, product_name)
        return "paypal", pid, url

    return "demo", "demo_%s" % order_ref, "%s/pay/demo/%s" % (config.PUBLIC_BASE_URL, token)
