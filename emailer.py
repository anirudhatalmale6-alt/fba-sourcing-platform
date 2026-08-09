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


def calculator_summary_email(lead, res, lead_token=None):
    """Plain text so it renders anywhere, including phone previews."""
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
    ]
    lines += _sig(lead_token)
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


def _sig(lead_token=None):
    out = ["", "Regards,", "The %s team" % config.BRAND_NAME]
    if config.WHATSAPP_NUMBER:
        out += ["", "Prefer to talk it through? WhatsApp us on +%s (%s)."
                % (config.WHATSAPP_NUMBER, config.WHATSAPP_HOURS)]
    if lead_token:
        out += ["", "---",
                "No longer want these? %s/unsubscribe/%s"
                % (config.PUBLIC_BASE_URL, lead_token)]
    return out


def sequence_hidden_costs(lead, res):
    """Step 1 - teach something concrete using their own figures."""
    name = ((lead["name"] or "there").split(" ") or ["there"])[0]
    product = lead["product_name"] or "your product"
    lines = ["Hi %s," % name, ""]
    if res and res.get("price", 0) > 0:
        taken = res["referral_fee"] + res["fba_fee"] + res["vat_due"]
        pct = taken / res["price"] * 100 if res["price"] else 0
        lines += [
            "A follow-up on %s, because there is one number most sellers never work out." % product,
            "",
            "On a %s sale, this is what leaves before you have paid for the product:" % _money(res["price"]),
            "",
            "  Amazon referral fee     %s" % _money(res["referral_fee"]),
            "  FBA fulfilment fee      %s" % _money(res["fba_fee"]),
            "  VAT to HMRC             %s" % _money(res["vat_due"]),
            "  ----------------------------------",
            "  Gone before cost        %s  (%.0f%% of the sale)" % (_money(taken), pct),
            "",
        ]
    else:
        lines += ["A quick follow-up on the calculator, because there is one number most "
                  "sellers never work out.", ""]
    lines += [
        "That is the part people model. Here is the part they miss, and it is usually what",
        "turns a profitable spreadsheet into a disappointing bank balance:",
        "",
        "1. ADVERTISING. A new listing does not rank on its own. Budget for it per unit from",
        "   day one, not as a marketing line you review later.",
        "",
        "2. RETURNS. You refund the customer the full price, Amazon keeps part of its fee, and",
        "   the unit often cannot be resold as new.",
        "",
        "3. STORAGE, AND THE Q4 SURCHARGE. Slow movers accumulate long-term storage fees, and",
        "   October to December costs several times the normal rate.",
        "",
        "4. THE CASH GAP. The factory wants its balance before shipping. Amazon settles on a",
        "   fortnightly cycle. Between those two facts sits every cash flow problem in this",
        "   business, and it is the reason profitable sellers still run out of money.",
        "",
        "5. IMPORT VAT. Reclaimable if you are registered, a dead cost if you are not. At any",
        "   real volume this is the single biggest lever most new sellers are not pulling.",
        "",
        "Go back to your figures and put a real number against advertising and returns. If the",
        "product still works, you have something. If it does not, you have just saved yourself",
        "an order you would have regretted.",
        "",
        "  %s/#calculator" % config.PUBLIC_BASE_URL,
    ]
    lines += _sig(lead["token"])
    return "The costs that are not on your Amazon fee estimate", "\n".join(lines)


def sequence_sourcing_advantage(lead, res):
    """Step 2 - the actual business, framed as the fix to the margin problem."""
    name = ((lead["name"] or "there").split(" ") or ["there"])[0]
    product = lead["product_name"] or "your product"
    lines = [
        "Hi %s," % name, "",
        "There are only two ways to fix a thin margin. Charge more, which Amazon rarely lets",
        "you do for long. Or buy better, which almost nobody does properly.",
        "",
        "Here is what buying better actually means, and it is what we do every day:",
        "",
        "FACTORY SOURCING. Most UK sellers are buying from a trading company without knowing",
        "it. It looks like a factory, quotes like a factory, and adds a margin to every unit",
        "you will ever order. We verify the manufacturer: business licence, export history and",
        "a video walk of the line.",
        "",
        "BULK PURCHASING. We consolidate orders across our clients, so a first order is priced",
        "the way a repeat buyer would be priced.",
        "",
        "QUALITY CHECKS. We inspect against a written checklist and hold the balance payment",
        "until it is right. After the container sails you have no leverage at all.",
        "",
        "SHIPPING AND IMPORT. Sea, rail and air compared on landed cost rather than habit.",
        "Commodity codes classified correctly, duty and VAT handled so it is reclaimed rather",
        "than written off.",
        "",
        "FBA DELIVERY AND PREP. FNSKU labelling, polybagging and carton marking done at source,",
        "delivered straight into your Amazon warehouse. Not to your garage.",
        "",
        "PRIVATE LABEL. Your brand on the product, with tooling and minimum order quantities",
        "negotiated on your behalf, so you are building an asset rather than reselling a",
        "generic that anyone can undercut next month.",
        "",
        "In our experience a direct factory quote lands fifteen to thirty percent under a first",
        "quote from a trading company. On %s that is usually the difference between" % product,
        "a product that works and one that does not.",
        "",
        "  %s/services" % config.PUBLIC_BASE_URL,
    ]
    lines += _sig(lead["token"])
    return "Two ways to fix a thin margin (one of them works)", "\n".join(lines)


def sequence_offer(lead, res):
    """Step 3 - the ask, with a reason to act rather than a discount."""
    name = ((lead["name"] or "there").split(" ") or ["there"])[0]
    product = lead["product_name"] or "your product"
    lines = ["Hi %s," % name, "",
             "Last one from me on %s." % product, ""]
    if res and res.get("landed_unit", 0) > 0:
        lines += [
            "Your figures came out at %s landed per unit, breaking even at %s."
            % (_money(res["landed_unit"]), _money(res["break_even"])),
            "",
        ]
    lines += [
        "Those numbers are only as good as the quotes behind them, and the two that move the",
        "result most are the two people are least sure about: what the factory should really",
        "be charging, and what the freight will actually cost.",
        "",
        "That is what the %s does. For %s our sourcing team:" % (config.AUDIT_NAME, _money(config.AUDIT_PRICE_GBP)),
        "",
        "  - re-quotes your product against our factory network",
        "  - prices the freight properly rather than by estimate",
        "  - checks whether your supplier is a factory or a reseller",
        "  - stress tests the margin against freight rises, price wars and ad costs",
        "  - tells you honestly whether this product is worth importing",
        "",
        "You get a written report, reviewed by a person before it reaches you, and a clear",
        "recommendation. If the answer is walk away, we will say so. That answer is worth more",
        "than the fee.",
        "",
        "  %s/audit" % config.PUBLIC_BASE_URL,
        "",
        "And if you would rather just talk it through first, reply to this email and we will.",
    ]
    lines += _sig(lead["token"])
    return "Is %s actually worth importing?" % product, "\n".join(lines)


SEQUENCE = [sequence_hidden_costs, sequence_sourcing_advantage, sequence_offer]


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
