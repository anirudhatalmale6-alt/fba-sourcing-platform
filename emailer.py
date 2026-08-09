"""Email delivery with a safety net.

If SMTP is configured the message goes out. If it is not, the message is still
composed and stored so it can be read in the admin outbox. That means the whole
funnel is testable before any mailbox exists, and nothing is ever lost.
"""
import smtplib
from email.message import EmailMessage

import config
import db


def send(to_addr, subject, body, kind="generic"):
    if not to_addr:
        return db.log_email(to_addr, subject, body, kind, "failed", "no recipient address")
    if not config.EMAIL_LIVE:
        return db.log_email(to_addr, subject, body, kind, "queued", "SMTP not configured")

    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
            if config.SMTP_TLS:
                server.starttls()
        with server:
            if config.SMTP_USER:
                server.login(config.SMTP_USER, config.SMTP_PASS)
            server.send_message(msg)
        return db.log_email(to_addr, subject, body, kind, "sent")
    except Exception as exc:                      # noqa: BLE001 - report, never crash the request
        return db.log_email(to_addr, subject, body, kind, "failed", str(exc)[:400])


def notify_admin(subject, body, kind="admin"):
    if config.ADMIN_NOTIFY_EMAIL:
        send(config.ADMIN_NOTIFY_EMAIL, subject, body, kind)
    else:
        db.log_email("(admin not configured)", subject, body, kind, "queued",
                     "ADMIN_NOTIFY_EMAIL not set")


def _money(x):
    return "GBP %.2f" % x


def calculator_summary_email(lead, res):
    """Plain text so it renders anywhere, including phone previews."""
    brand = config.BRAND_NAME
    name = (lead.get("name") or "there").split(" ")[0]
    product = lead.get("product_name") or "your product"
    lines = [
        "Hi %s," % name,
        "",
        "Here is the landed cost and profit breakdown for %s." % product,
        "",
        "YOUR NUMBERS",
        "  Landed cost per unit      %s" % _money(res["landed_unit"]),
        "  Break-even selling price  %s" % _money(res["break_even"]),
    ]
    if res["price"] > 0:
        lines += [
            "  Your selling price        %s" % _money(res["price"]),
            "  Profit per unit           %s" % _money(res["profit_unit"]),
            "  Net margin                %.1f%%" % res["margin_pct"],
            "  Return on investment      %.0f%%" % res["roi_pct"],
            "  Profit on %d units        %s" % (int(res["qty"]), _money(res["profit_total"])),
        ]
    lines += [
        "  Cash needed up front      %s" % _money(res["cash_out"]),
        "",
        "WHAT THIS MEANS",
        "  %s" % res["verdict_note"],
        "",
    ]
    if res["flags"]:
        lines.append("WORTH CHECKING")
        for f in res["flags"][:5]:
            lines.append("  - %s" % f)
        lines.append("")
    lines += [
        "A reminder that these figures are only as good as the quotes behind them.",
        "Freight and duty are where most first-time importers get caught out.",
        "",
        "If you want our sourcing team to go through this product properly, the",
        "%s is %s. We check your supplier, re-quote the product" % (config.AUDIT_NAME, _money(config.AUDIT_PRICE_GBP)),
        "against our factory network, price the freight and tell you honestly",
        "whether it is worth importing.",
        "",
        "  %s/audit" % config.PUBLIC_BASE_URL,
        "",
        "Regards,",
        "The %s team" % brand,
    ]
    return "Your landed cost breakdown for %s" % product, "\n".join(lines)


def order_confirmation_email(order, lead):
    name = ((lead["name"] if lead else "") or "there").split(" ")[0]
    url = "%s/order/%s" % (config.PUBLIC_BASE_URL, order["token"])
    body = "\n".join([
        "Hi %s," % name,
        "",
        "Thank you, your %s is confirmed." % order["service"],
        "",
        "  Reference   %s" % order["reference"],
        "  Amount      %s" % _money(order["amount_gbp"]),
        "",
        "Next step: tell us about the product so the team can start. It takes a",
        "couple of minutes and the more detail you give, the sharper the audit.",
        "",
        "  %s" % url,
        "",
        "Once the questionnaire is in, your report is prepared and a sourcing",
        "specialist reviews it before it reaches you.",
        "",
        "Regards,",
        "The %s team" % config.BRAND_NAME,
    ])
    return "Order confirmed - %s" % order["reference"], body


def report_ready_email(order, lead):
    name = ((lead["name"] if lead else "") or "there").split(" ")[0]
    url = "%s/report/%s" % (config.PUBLIC_BASE_URL, order["token"])
    body = "\n".join([
        "Hi %s," % name,
        "",
        "Your %s is ready." % order["service"],
        "",
        "  %s" % url,
        "",
        "It covers your landed cost, the margin at your target price, the risks",
        "we can see in the numbers and what we would do next on this product.",
        "",
        "If you would like us to source it properly, reply and we will pick it up",
        "from there.",
        "",
        "Regards,",
        "The %s team" % config.BRAND_NAME,
    ])
    return "Your audit report is ready - %s" % order["reference"], body
