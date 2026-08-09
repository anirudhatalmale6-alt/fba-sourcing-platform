"""FastAPI application: calculator, funnel, payments, reports and admin."""
import hashlib
import hmac
import json
import time

from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import db
import emailer
import payments
import reportgen
import sequences
from calc import Inputs, calculate, summarise

app = FastAPI(title="%s" % config.BRAND_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))

db.init()


@app.on_event("startup")
async def _start_sequence_runner():
    if config.SEQUENCE_ENABLED:
        import asyncio
        app.state.seq_task = asyncio.create_task(sequences.ticker())


@app.on_event("shutdown")
async def _stop_sequence_runner():
    task = getattr(app.state, "seq_task", None)
    if task:
        task.cancel()


# --- template globals ------------------------------------------------------
def base_ctx(request):
    return {
        "request": request,
        "cfg": config,
        "brand": config.BRAND_NAME,
        "tagline": config.BRAND_TAGLINE,
        "audit_price": config.AUDIT_PRICE_GBP,
        "audit_name": config.AUDIT_NAME,
        "starter_name": config.STARTER_NAME,
        "starter_price": config.STARTER_PRICE_GBP,
        "launch_name": config.LAUNCH_NAME,
        "launch_from": config.LAUNCH_PRICE_FROM,
        "launch_to": config.LAUNCH_PRICE_TO,
        "premium_name": config.PREMIUM_NAME,
        "premium_price": config.PREMIUM_PRICE_GBP,
        "services": config.SOURCING_SERVICES,
        "advantage": config.CHINA_ADVANTAGE,
        "whatsapp": config.WHATSAPP_NUMBER,
        "whatsapp_link": _whatsapp_link(),
        "year": time.strftime("%Y"),
    }


def _whatsapp_link():
    if not config.WHATSAPP_NUMBER:
        return ""
    import urllib.parse
    return "https://wa.me/%s?text=%s" % (
        config.WHATSAPP_NUMBER, urllib.parse.quote(config.WHATSAPP_PREFILL))


def money(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "&pound;0.00"
    if v < 0:
        return "&minus;&pound;" + format(abs(v), ",.2f")
    return "&pound;" + format(v, ",.2f")


def price(x):
    """Whole-pound price with a thousands separator: 1500 -> 1,500."""
    try:
        return format(float(x), ",.0f")
    except (TypeError, ValueError):
        return "0"


templates.env.filters["money"] = money
templates.env.filters["price"] = price
templates.env.globals["cfg"] = config


# --- admin session ---------------------------------------------------------
COOKIE = "hl_admin"


def _sign(value):
    mac = hmac.new(config.SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]
    return "%s.%s" % (value, mac)


def _verify(raw):
    if not raw or "." not in raw:
        return False
    value, mac = raw.rsplit(".", 1)
    if not hmac.compare_digest(_sign(value), raw):
        return False
    try:
        return float(value.split("|")[1]) > time.time()
    except (IndexError, ValueError):
        return False


def require_admin(request: Request):
    if not _verify(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=307, headers={"Location": "/admin/login"})
    return True


# --- public pages ----------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    ctx = base_ctx(request)
    ctx["defaults"] = {
        "vat_rate": config.DEFAULT_VAT_RATE,
        "referral_pct": config.DEFAULT_REFERRAL_PCT,
        "duty_pct": config.DEFAULT_DUTY_PCT,
        "fx": config.DEFAULT_FX_USD_GBP,
    }
    return templates.TemplateResponse("index.html", ctx)


@app.get("/services", response_class=HTMLResponse)
def services_page(request: Request):
    return templates.TemplateResponse("services.html", base_ctx(request))


@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, cancelled: int = 0):
    ctx = base_ctx(request)
    ctx["cancelled"] = bool(cancelled)
    ctx["providers"] = payments.available()
    ctx["lead_token"] = request.query_params.get("lead", "")
    return templates.TemplateResponse("audit.html", ctx)


@app.get("/contact", response_class=HTMLResponse)
def contact_page(request: Request, sent: int = 0):
    ctx = base_ctx(request)
    ctx["sent"] = bool(sent)
    return templates.TemplateResponse("contact.html", ctx)


@app.post("/contact")
async def contact_submit(request: Request):
    form = dict(await request.form())
    if form.get("website"):                        # honeypot
        return RedirectResponse("/contact?sent=1", status_code=303)
    db.create_enquiry(form)
    emailer.notify_admin(
        "New enquiry from %s" % (form.get("name") or "unknown"),
        "Name: %s\nEmail: %s\nPhone: %s\nInterest: %s\n\n%s" % (
            form.get("name"), form.get("email"), form.get("phone"),
            form.get("service"), form.get("message")),
        kind="enquiry")
    return RedirectResponse("/contact?sent=1", status_code=303)


# --- calculator ------------------------------------------------------------
@app.post("/calculate", response_class=HTMLResponse)
async def do_calculate(request: Request):
    form = dict(await request.form())
    res = calculate(Inputs.from_form(form))
    ctx = base_ctx(request)
    ctx.update({"res": res, "gated": True})
    return templates.TemplateResponse("_results.html", ctx)


@app.post("/lead", response_class=HTMLResponse)
async def capture_lead(request: Request):
    form = dict(await request.form())
    if form.get("website"):
        return HTMLResponse("<p>Thanks.</p>")
    email = (form.get("email") or "").strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        return HTMLResponse(
            "<div class='formerr'>That email address does not look right. "
            "Please check it and try again.</div>", status_code=200)

    res = calculate(Inputs.from_form(form))
    lead_id, token = db.create_lead(form, res["inputs"], res, summarise(res))
    subject, body = emailer.calculator_summary_email(form, res, token)
    emailer.send(email, subject, body, kind="calc_summary")
    sequences.schedule_for_lead(lead_id)
    emailer.notify_admin(
        "New calculator lead: %s" % (form.get("product_name") or "unnamed product"),
        "Name: %s\nEmail: %s\nPhone: %s\nProduct: %s\nSupplier: %s\n\n%s\n\nNotes: %s" % (
            form.get("name"), email, form.get("phone"), form.get("product_name"),
            form.get("supplier_details"), summarise(res), form.get("notes")),
        kind="lead_alert")

    ctx = base_ctx(request)
    ctx.update({"res": res, "gated": False, "lead_token": token,
                "lead_name": (form.get("name") or "").split(" ")[0]})
    return templates.TemplateResponse("_results.html", ctx)


# --- checkout --------------------------------------------------------------
@app.post("/checkout")
async def checkout(request: Request):
    form = dict(await request.form())
    provider = (form.get("provider") or "").strip() or payments.available()[0]
    lead_token = (form.get("lead_token") or "").strip()
    lead = db.get_lead_by_token(lead_token) if lead_token else None

    if not lead:
        # Buying without running the calculator first: capture the essentials so
        # the order is still attached to a person.
        email = (form.get("email") or "").strip()
        if "@" not in email:
            return RedirectResponse("/audit?err=email", status_code=303)
        blank = calculate(Inputs.from_form({}))
        lead_id, lead_token = db.create_lead(form, blank["inputs"], blank,
                                             "Purchased audit without using the calculator.",
                                             source="direct")
        lead = db.get_lead(lead_id)

    order_id, ref, token = db.create_order(
        lead["id"], config.AUDIT_NAME, config.AUDIT_PRICE_GBP, provider)
    try:
        used, pref, url = payments.start(
            provider, ref, token, config.AUDIT_PRICE_GBP,
            "%s - %s" % (config.AUDIT_NAME, config.BRAND_NAME), lead["email"])
    except payments.PaymentError as exc:
        emailer.notify_admin("Payment start failed for %s" % ref, str(exc), kind="error")
        return RedirectResponse("/audit?err=payment", status_code=303)
    db.set_provider_ref(order_id, used, pref)
    return RedirectResponse(url, status_code=303)


@app.get("/pay/demo/{token}", response_class=HTMLResponse)
def demo_pay(request: Request, token: str):
    order = db.get_order_by_token(token)
    if not order:
        raise HTTPException(404)
    ctx = base_ctx(request)
    ctx["order"] = order
    return templates.TemplateResponse("demo_pay.html", ctx)


@app.post("/pay/demo/{token}")
def demo_pay_confirm(token: str):
    order = db.get_order_by_token(token)
    if not order:
        raise HTTPException(404)
    _settle(order)
    return RedirectResponse("/order/%s?paid=1" % token, status_code=303)


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    raw = await request.body()
    if config.STRIPE_WEBHOOK_SECRET:
        sig = request.headers.get("stripe-signature", "")
        if not _stripe_sig_ok(raw, sig):
            raise HTTPException(400, "bad signature")
    try:
        event = json.loads(raw.decode())
    except ValueError:
        raise HTTPException(400, "bad payload")
    if event.get("type") == "checkout.session.completed":
        obj = event["data"]["object"]
        token = (obj.get("metadata") or {}).get("order_token")
        order = db.get_order_by_token(token) if token else None
        if not order and obj.get("id"):
            order = db.get_order_by_provider_ref(obj["id"])
        if order and order["status"] != "paid":
            _settle(order)
    return JSONResponse({"received": True})


def _stripe_sig_ok(raw, header):
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        signed = ("%s.%s" % (parts["t"], raw.decode())).encode()
        expected = hmac.new(config.STRIPE_WEBHOOK_SECRET.encode(), signed,
                            hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, parts["v1"])
    except Exception:                              # noqa: BLE001
        return False


@app.get("/paypal/capture")
def paypal_return(token_ref: str = "", token: str = ""):
    order = db.get_order_by_token(token_ref)
    if not order:
        raise HTTPException(404)
    try:
        if payments.paypal_capture(order["provider_ref"]):
            _settle(order)
    except payments.PaymentError as exc:
        emailer.notify_admin("PayPal capture failed for %s" % order["reference"],
                             str(exc), kind="error")
    return RedirectResponse("/order/%s?paid=1" % token_ref, status_code=303)


def _settle(order):
    """Mark paid, confirm to the customer, alert the team. Idempotent."""
    if order["status"] == "paid":
        return
    db.mark_paid(order["id"])
    order = db.get_order(order["id"])
    lead = db.get_lead(order["lead_id"]) if order["lead_id"] else None
    if lead:
        sequences.stop_for_lead(lead["id"])   # they bought; stop selling to them
    if lead and lead["email"]:
        subject, body = emailer.order_confirmation_email(order, lead)
        emailer.send(lead["email"], subject, body, kind="order_confirmation")
    emailer.notify_admin(
        "PAID: %s %s" % (order["reference"], money(order["amount_gbp"]).replace("&pound;", "GBP ")),
        "Service: %s\nCustomer: %s <%s>\nQuestionnaire: %s/order/%s" % (
            order["service"], lead["name"] if lead else "?", lead["email"] if lead else "?",
            config.PUBLIC_BASE_URL, order["token"]),
        kind="sale")


# --- post-purchase ---------------------------------------------------------
@app.get("/order/{token}", response_class=HTMLResponse)
def order_page(request: Request, token: str, paid: int = 0):
    order = db.get_order_by_token(token)
    if not order:
        raise HTTPException(404)
    lead = db.get_lead(order["lead_id"]) if order["lead_id"] else None
    ctx = base_ctx(request)
    ctx.update({"order": order, "lead": lead, "just_paid": bool(paid),
                "questionnaire": json.loads(order["questionnaire"]) if order["questionnaire"] else {}})
    return templates.TemplateResponse("order.html", ctx)


@app.post("/order/{token}/questionnaire")
async def order_questionnaire(request: Request, token: str):
    order = db.get_order_by_token(token)
    if not order:
        raise HTTPException(404)
    form = dict(await request.form())
    form.pop("website", None)
    db.save_questionnaire(order["id"], form)
    order = db.get_order(order["id"])
    lead = db.get_lead(order["lead_id"]) if order["lead_id"] else None

    html = reportgen.build_for_order(order, lead)
    db.save_report(order["id"], html, "auto")
    order = db.get_order(order["id"])
    if lead and lead["email"]:
        subject, body = emailer.report_ready_email(order, lead)
        emailer.send(lead["email"], subject, body, kind="report_ready")
    emailer.notify_admin(
        "Questionnaire in, draft report ready: %s" % order["reference"],
        "Review and upgrade before the customer relies on it:\n%s/admin/order/%s" % (
            config.PUBLIC_BASE_URL, order["id"]), kind="report")
    return RedirectResponse("/report/%s?new=1" % token, status_code=303)


@app.get("/report/{token}", response_class=HTMLResponse)
def report_view(token: str, print: int = 0):
    order = db.get_order_by_token(token)
    if not order:
        raise HTTPException(404)
    if order["status"] != "paid":
        return HTMLResponse("<p>This report is not available yet.</p>", status_code=402)
    if not order["report_html"]:
        lead = db.get_lead(order["lead_id"]) if order["lead_id"] else None
        html = reportgen.build_for_order(order, lead)
        db.save_report(order["id"], html, "auto")
        return HTMLResponse(html)
    return HTMLResponse(order["report_html"])


@app.get("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(request: Request, token: str):
    ok = db.unsubscribe_lead(token) is not None
    ctx = base_ctx(request)
    ctx["ok"] = ok
    return templates.TemplateResponse("unsubscribe.html", ctx)


# --- admin -----------------------------------------------------------------
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, err: int = 0):
    ctx = base_ctx(request)
    ctx["err"] = bool(err)
    return templates.TemplateResponse("admin/login.html", ctx)


@app.post("/admin/login")
def admin_login(username: str = Form(...), password: str = Form(...)):
    if not (hmac.compare_digest(username, config.ADMIN_USER)
            and hmac.compare_digest(password, config.ADMIN_PASS)):
        return RedirectResponse("/admin/login?err=1", status_code=303)
    value = "%s|%d" % (username, int(time.time()) + 60 * 60 * 12)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(COOKIE, _sign(value), httponly=True, samesite="lax", max_age=60 * 60 * 12)
    return resp


@app.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, _=Depends(require_admin)):
    ctx = base_ctx(request)
    ctx.update({"stats": db.stats(), "leads": db.list_leads(8), "orders": db.list_orders(8)})
    return templates.TemplateResponse("admin/dashboard.html", ctx)


@app.get("/admin/leads", response_class=HTMLResponse)
def admin_leads(request: Request, _=Depends(require_admin)):
    ctx = base_ctx(request)
    ctx["leads"] = db.list_leads()
    return templates.TemplateResponse("admin/leads.html", ctx)


@app.get("/admin/orders", response_class=HTMLResponse)
def admin_orders(request: Request, _=Depends(require_admin)):
    ctx = base_ctx(request)
    ctx["orders"] = db.list_orders()
    return templates.TemplateResponse("admin/orders.html", ctx)


@app.get("/admin/order/{order_id}", response_class=HTMLResponse)
def admin_order(request: Request, order_id: int, _=Depends(require_admin), saved: int = 0):
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(404)
    lead = db.get_lead(order["lead_id"]) if order["lead_id"] else None
    ctx = base_ctx(request)
    ctx.update({
        "order": order, "lead": lead, "saved": bool(saved),
        "questionnaire": json.loads(order["questionnaire"]) if order["questionnaire"] else {},
        "calc": json.loads(lead["calc_results"]) if lead and lead["calc_results"] else None,
    })
    return templates.TemplateResponse("admin/order.html", ctx)


@app.post("/admin/order/{order_id}/notes")
def admin_order_notes(order_id: int, notes: str = Form(""), _=Depends(require_admin)):
    """Add the specialist's own analysis, then rebuild so it lands in the report."""
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(404)
    lead = db.get_lead(order["lead_id"]) if order["lead_id"] else None
    db.save_report(order_id, order["report_html"] or "", order["report_status"], notes)
    order = db.get_order(order_id)
    html = reportgen.build_for_order(order, lead)
    db.save_report(order_id, html, "manual_review" if notes.strip() else "auto", notes)
    return RedirectResponse("/admin/order/%d?saved=1" % order_id, status_code=303)


@app.post("/admin/order/{order_id}/rebuild")
def admin_order_rebuild(order_id: int, _=Depends(require_admin)):
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(404)
    lead = db.get_lead(order["lead_id"]) if order["lead_id"] else None
    html = reportgen.build_for_order(order, lead)
    db.save_report(order_id, html, order["report_status"] or "auto")
    return RedirectResponse("/admin/order/%d?saved=1" % order_id, status_code=303)


@app.post("/admin/order/{order_id}/deliver")
def admin_order_deliver(order_id: int, _=Depends(require_admin)):
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(404)
    lead = db.get_lead(order["lead_id"]) if order["lead_id"] else None
    db.save_report(order_id, order["report_html"] or "", "delivered")
    if lead and lead["email"]:
        subject, body = emailer.report_ready_email(order, lead)
        emailer.send(lead["email"], subject, body, kind="report_delivered")
    return RedirectResponse("/admin/order/%d?saved=1" % order_id, status_code=303)


@app.post("/admin/order/{order_id}/markpaid")
def admin_mark_paid(order_id: int, _=Depends(require_admin)):
    """For bank transfers and anything else settled outside the gateways."""
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(404)
    _settle(order)
    return RedirectResponse("/admin/order/%d?saved=1" % order_id, status_code=303)


@app.get("/admin/sequence", response_class=HTMLResponse)
def admin_sequence(request: Request, _=Depends(require_admin)):
    ctx = base_ctx(request)
    ctx["jobs"] = db.list_sequence_jobs()
    ctx["steps"] = ["Results summary (immediate)", "Hidden Amazon costs",
                    "China sourcing advantage", "Product review offer"]
    ctx["hours"] = config.SEQ_STEP_HOURS
    return templates.TemplateResponse("admin/sequence.html", ctx)


@app.post("/admin/sequence/run")
def admin_sequence_run(_=Depends(require_admin)):
    """Send anything already due now, rather than waiting for the next tick."""
    sequences.run_due(limit=100)
    return RedirectResponse("/admin/sequence", status_code=303)


@app.get("/admin/emails", response_class=HTMLResponse)
def admin_emails(request: Request, _=Depends(require_admin)):
    ctx = base_ctx(request)
    ctx["emails"] = db.list_emails()
    return templates.TemplateResponse("admin/emails.html", ctx)


@app.get("/admin/email/{email_id}", response_class=HTMLResponse)
def admin_email(request: Request, email_id: int, _=Depends(require_admin)):
    row = db.get_email(email_id)
    if not row:
        raise HTTPException(404)
    ctx = base_ctx(request)
    ctx["mail"] = row
    return templates.TemplateResponse("admin/email.html", ctx)


@app.get("/admin/enquiries", response_class=HTMLResponse)
def admin_enquiries(request: Request, _=Depends(require_admin)):
    ctx = base_ctx(request)
    ctx["enquiries"] = db.list_enquiries()
    return templates.TemplateResponse("admin/enquiries.html", ctx)


@app.get("/admin/export/leads.csv")
def export_leads(_=Depends(require_admin)):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "created", "name", "email", "phone", "product",
                "supplier", "summary", "source"])
    for r in db.list_leads(5000):
        w.writerow([r["id"], r["created_at"], r["name"], r["email"], r["phone"],
                    r["product_name"], r["supplier_details"], r["summary"], r["source"]])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": "attachment; filename=leads.csv"})


@app.get("/healthz")
def healthz():
    return {"ok": True, "payments": payments.available(), "email_live": config.EMAIL_LIVE}
