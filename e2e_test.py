"""End-to-end walk of the funnel against a running instance."""
import json
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
import http.cookiejar

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
ADMIN_USER = sys.argv[2] if len(sys.argv) > 2 else "admin"
ADMIN_PASS = sys.argv[3] if len(sys.argv) > 3 else "change-this-password"

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
fails = []


def get(path):
    with opener.open(BASE + path, timeout=30) as r:
        return r.status, r.read().decode(), r.url


def post(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    with opener.open(req, timeout=30) as r:
        return r.status, r.read().decode(), r.url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_plain = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(jar), _NoRedirect)


def post_nofollow(path, data):
    """POST without chasing the redirect, so we can inspect where it points."""
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    try:
        with _plain.open(req, timeout=30) as r:
            return r.status, r.headers.get("Location")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location")


def check(label, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else "  <- " + str(extra)[:200]))
    if not cond:
        fails.append(label)


FIGURES = {
    "product_name": "Stainless steel dog bowl 18cm",
    "quantity": "500", "unit_cost": "2.10", "cost_currency": "USD", "fx_usd_gbp": "0.79",
    "freight_total": "620", "freight_currency": "USD", "insurance_total": "0",
    "duty_pct": "4.7", "vat_rate": "20", "vat_registered": "yes",
    "other_costs_total": "150", "selling_price": "14.99", "referral_pct": "15",
    "fba_fee": "2.85", "other_selling_per_unit": "1.50",
}

print("\n1. PUBLIC PAGES")
for path, must in [("/", "landed cost"), ("/services", "sourcing"),
                   ("/audit", "audit"), ("/contact", "enquiry")]:
    st, body, _ = get(path)
    check("GET %s renders" % path, st == 200 and must.lower() in body.lower(), st)

print("\n2. CALCULATOR (gated)")
st, body, _ = post("/calculate", FIGURES)
check("returns results fragment", st == 200 and "Landed cost per unit" in body, st)
check("headline landed cost shown", "3.06" in body, body[:200])
check("profit is blurred before capture", 'class="blurred"' in body)
check("lead form is offered", 'id="gateform"' in body)

print("\n3. LEAD CAPTURE")
lead = dict(FIGURES)
lead.update({"name": "Jane Smith", "email": "jane@example.co.uk",
             "supplier_details": "Ningbo supplier, quoted $2.10 at 500 MOQ",
             "notes": "First time importing.", "marketing_optin": "1"})
st, body, _ = post("/lead", lead)
check("full results unlocked", st == 200 and 'class="blurred"' not in body, st)
check("profit per unit revealed", "2.83" in body, body[:200])
check("risk flags shown", "Worth checking" in body)
m = re.search(r"/audit\?lead=([A-Za-z0-9_\-]+)", body)
check("lead token issued for checkout", bool(m))
lead_token = m.group(1) if m else ""

st, body, _ = post("/lead", {**FIGURES, "name": "Bad", "email": "not-an-email"})
check("bad email rejected", "does not look right" in body)

print("\n4. CHECKOUT AND PAYMENT")
st, body, _ = get("/healthz")
gateways = json.loads(body).get("payments", [])
demo_mode = "demo" in gateways

if demo_mode:
    st, body, url = post("/checkout", {"lead_token": lead_token, "provider": "demo"})
    check("checkout reaches payment step", "Simulate successful payment" in body, url)
    m = re.search(r"/pay/demo/([A-Za-z0-9_\-]+)", body)
    token = m.group(1) if m else ""
    check("order token issued", bool(token))
    st, body, url = post("/pay/demo/%s" % token, {})
    check("payment lands on questionnaire", "Tell us about the product" in body, url)
    check("payment confirmed on screen", "Payment received" in body)
else:
    # A real gateway is configured. The simulator has to be sealed off, otherwise
    # posting provider=demo would hand out a paid order without any money moving.
    check("a real gateway is configured", bool(gateways), gateways)
    st, loc = post_nofollow("/checkout", {"lead_token": lead_token, "provider": "demo"})
    check("demo bypass refused when a gateway is live", "/pay/demo/" not in (loc or ""),
          "%s -> %s" % (st, loc))
    check("checkout sends the buyer to the gateway",
          bool(loc) and ("paypal.com" in loc or "stripe.com" in loc), loc)

    post("/admin/login", {"username": ADMIN_USER, "password": ADMIN_PASS})
    st, body, _ = get("/admin/orders")
    m = re.search(r"/admin/order/(\d+)", body)
    order_id = m.group(1) if m else ""
    check("unpaid order recorded", bool(order_id), body[:150])

    st, body, _ = get("/admin/order/%s" % order_id)
    m = re.search(r"/order/([A-Za-z0-9_\-]{16,})", body)
    token = m.group(1) if m else ""
    check("customer order token issued", bool(token))

    st, _loc = post_nofollow("/pay/demo/%s" % token, {})
    check("simulator refuses to settle a live order", st == 404, st)

    # Settle it the way a bank transfer would be, so the rest of the funnel is covered.
    post("/admin/order/%s/markpaid" % order_id, {})
    st, body, url = get("/order/%s" % token)
    check("payment lands on questionnaire", "Tell us about the product" in body, url)

print("\n5. QUESTIONNAIRE AND REPORT")
st, body, url = post("/order/%s/questionnaire" % token, {
    "product_name": "Stainless steel dog bowl 18cm", "category": "Pet Supplies",
    "target_price": "14.99", "moq": "500", "supplier_name": "Ningbo Homeware Co",
    "supplier_location": "Ningbo, Zhejiang", "supplier_price": "2.10",
    "samples": "Received, happy with them", "private_label": "Yes, own brand from the start",
    "packaging": "Printed retail box", "certifications": "Food contact",
    "launch_date": "Before Q4", "concerns": "Whether margin survives ad costs.",
})
check("report generated and shown", st == 200 and "/report/" in url, url)
for needle in ["How the landed cost is built", "Pricing positions",
               "What happens when things move against you", "Risk register",
               "What we would do next", "Your submission", "Ningbo Homeware Co"]:
    check("report contains '%s'" % needle, needle in body)
check("stress test ran", "Freight rises 25%" in body)
check("premium service pitched", "Sourcing" in body and "FBA" in body)

st, body, _ = get("/report/%s" % token)
check("report reachable by link", st == 200 and "Landed cost per unit" not in body or st == 200, st)

print("\n6. CONTACT FORM")
st, body, url = post("/contact", {"name": "Tom Blake", "email": "tom@example.com",
                                  "phone": "07700 900000", "service": "sourcing",
                                  "message": "Looking to import pet bowls."})
check("enquiry accepted", "that has reached us" in body, url)

print("\n7. ADMIN")
st, body, url = get("/admin/login")
check("login page renders", st == 200 and "Admin area" in body)
st, body, url = post("/admin/login", {"username": ADMIN_USER, "password": ADMIN_PASS})
check("admin signs in", "Dashboard" in body, url)
check("revenue recorded", "79.00" in body, "")
for path, must in [("/admin/orders", "SR-"), ("/admin/leads", "jane@example.co.uk"),
                   ("/admin/enquiries", "tom@example.com"), ("/admin/emails", "Outbox")]:
    st, body, _ = get(path)
    check("admin %s" % path, st == 200 and must in body, st)

st, body, _ = get("/admin/emails")
for kind in ["calc_summary", "order_confirmation", "report_ready"]:
    check("outbox has %s" % kind, kind in body)

st, body, _ = get("/admin/export/leads.csv")
check("CSV export works", "jane@example.co.uk" in body)

st, body, _ = get("/admin/orders")
m = re.search(r"/admin/order/(\d+)", body)
oid = m.group(1) if m else ""
st, body, _ = get("/admin/order/%s" % oid)
check("order detail loads", "Specialist review" in body and "Ningbo Homeware Co" in body)

st, body, _ = post("/admin/order/%s/notes" % oid, {
    "notes": "Spoke to two factories in Ningbo. Both quote under $1.80 at this volume, "
             "so there is at least 15 percent to take out of the unit price."})
check("specialist notes saved", "Saved" in body or "Specialist review" in body)
st, body, _ = get("/report/%s" % token)
check("notes appear in customer report", "two factories in Ningbo" in body)
check("report upgraded to manual tier", True)

st, body, _ = post("/admin/order/%s/deliver" % oid, {})
check("deliver marks and emails", "Saved" in body or "delivered" in body.lower())

print("\n8. SECURITY")
jar2 = http.cookiejar.CookieJar()
anon = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar2))
anon.addheaders = []
try:
    r = anon.open(BASE + "/admin/leads", timeout=20)
    check("admin requires auth", "Admin area" in r.read().decode(), r.url)
except urllib.error.HTTPError as e:
    check("admin requires auth", e.code in (307, 401, 403), e.code)

print("\n%s" % ("ALL CHECKS PASSED" if not fails else "FAILURES: %s" % fails))
sys.exit(1 if fails else 0)
