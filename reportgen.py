"""Automated audit report builder.

Produces a self-contained HTML report from the calculator inputs plus the
post-purchase questionnaire. It is written to stand on its own as the automated
tier, and to give a human reviewer a solid draft to sharpen for the premium
tier rather than a blank page.
"""
import html
import json
from datetime import datetime, timezone

import config
from calc import Inputs, calculate


def _m(x):
    """Sign goes outside the currency symbol, the way a ledger reads."""
    if x < 0:
        return "&minus;&pound;%s" % format(abs(x), ",.2f")
    return "&pound;%s" % format(x, ",.2f")


def _pct(x):
    return "%.1f%%" % x


def _esc(x):
    return html.escape(str(x or "")).replace("\n", "<br>")


def _scenarios(res):
    """Re-run the model under conditions that commonly bite importers."""
    base = Inputs(**res["inputs"])
    out = []

    def run(label, note, **changes):
        data = dict(res["inputs"])
        data.update(changes)
        r = calculate(Inputs(**data))
        out.append({
            "label": label, "note": note,
            "profit": r["profit_unit"], "margin": r["margin_pct"], "roi": r["roi_pct"],
            "delta": r["profit_unit"] - res["profit_unit"],
        })

    out.append({"label": "Your figures as entered", "note": "The baseline.",
                "profit": res["profit_unit"], "margin": res["margin_pct"],
                "roi": res["roi_pct"], "delta": 0.0})
    run("Freight rises 25%", "Container rates move constantly and quotes expire.",
        freight_total=base.freight_total * 1.25)
    run("Supplier price rises 10%", "Common at reorder once the sample price has done its job.",
        unit_cost=base.unit_cost * 1.10)
    run("You discount 10% to win the buy box", "Price wars are normal in a crowded category.",
        selling_price=base.selling_price * 0.90)
    run("Advertising costs £2 per unit", "Most new listings need paid traffic to rank.",
        other_selling_per_unit=base.other_selling_per_unit + 2.0)
    run("Duty is 2 points higher than assumed", "Commodity code disputes are common.",
        duty_pct=base.duty_pct + 2.0)
    run("All of the above together", "The realistic bad week, not the worst case.",
        freight_total=base.freight_total * 1.25,
        unit_cost=base.unit_cost * 1.10,
        selling_price=base.selling_price * 0.90,
        other_selling_per_unit=base.other_selling_per_unit + 2.0,
        duty_pct=base.duty_pct + 2.0)
    return out


def _price_ladder(res):
    """Profit at a spread of price points around break-even."""
    base = Inputs(**res["inputs"])
    anchor = res["price"] if res["price"] > 0 else res["recommended_price"]
    if anchor <= 0:
        return []
    rows = []
    for mult in (0.85, 0.95, 1.0, 1.10, 1.25):
        data = dict(res["inputs"])
        data["selling_price"] = anchor * mult
        r = calculate(Inputs(**data))
        rows.append({
            "price": r["price"], "profit": r["profit_unit"],
            "margin": r["margin_pct"], "roi": r["roi_pct"],
            "current": abs(mult - 1.0) < 1e-9,
        })
    return rows


def _recommendations(res, q):
    """Actionable next steps, driven by what the numbers actually say."""
    recs = []
    margin, roi = res["margin_pct"], res["roi_pct"]

    if res["price"] <= 0:
        recs.append(("Set a target price first",
                     "Work back from the shelf price your competitors hold, not forward "
                     "from your cost. Amazon is a price-led marketplace."))
    elif res["profit_unit"] <= 0:
        recs.append(("Do not place this order as specified",
                     "Every unit sold loses money. The fix is either a materially lower "
                     "factory price, cheaper freight per unit through larger volume, or "
                     "a different product. Re-quoting is the first thing we would do."))
    elif margin < 15 or roi < 50:
        recs.append(("Re-quote before committing",
                     "The margin is too thin to absorb a bad month. In our experience a "
                     "direct factory quote lands 15 to 30 percent under a first quote "
                     "from a trading company, which is usually the difference between "
                     "this product working and not."))
    else:
        recs.append(("The economics support an order",
                     "Protect the margin by locking the price and lead time in writing "
                     "before you pay a deposit."))

    if res["inputs"]["quantity"] < 300:
        recs.append(("Model a larger first order",
                     "Per-unit freight and setup costs fall sharply with volume. Run the "
                     "numbers again at two and three times the quantity before deciding, "
                     "then weigh that against the cash it ties up."))
    if not res["inputs"]["vat_registered"]:
        recs.append(("Review VAT registration",
                     "Unregistered, the import VAT you pay at the border is a dead cost. "
                     "Registered, you reclaim it. At any real volume this is normally the "
                     "single largest improvement available to you."))
    if res["inputs"]["duty_pct"] <= 0:
        recs.append(("Confirm the commodity code",
                     "A zero duty rate is unusual. Getting the code wrong is expensive to "
                     "unwind once goods are on the water."))

    supplier = (q.get("supplier_name") or "").strip() if q else ""
    if not supplier:
        recs.append(("Get competing factory quotes",
                     "With no supplier fixed you are in the strongest position you will "
                     "ever be in. Three quotes on identical written specs is the cheapest "
                     "leverage in importing."))
    else:
        recs.append(("Verify the supplier properly",
                     "Confirm %s is the factory and not a reseller: business licence, "
                     "audit report and a video walk of the line. Resellers add a margin "
                     "layer you are paying for without seeing." % html.escape(supplier)))

    recs.append(("Inspect before the balance payment",
                 "A pre-shipment inspection against a written checklist costs a fraction "
                 "of a rejected container and is the cheapest insurance in this process."))
    return recs


def build_report(order, lead, res, questionnaire=None):
    q = questionnaire or {}
    inputs = res["inputs"]
    product = (q.get("product_name") or inputs.get("product_name")
               or (lead["product_name"] if lead else "") or "Your product")
    client = (lead["name"] if lead else "") or "Client"
    generated = datetime.now(timezone.utc).strftime("%d %B %Y")
    scen = _scenarios(res)
    ladder = _price_ladder(res)
    recs = _recommendations(res, q)

    verdict_copy = {
        "strong": ("Proceed", "The product carries enough margin to survive normal trading pressure."),
        "workable": ("Proceed with care", "The product works, but with less headroom than we would like to see."),
        "thin": ("Re-quote first", "The margin is too tight to absorb the ordinary shocks of importing."),
        "loss": ("Do not proceed as costed", "The product loses money on every unit at the price given."),
        "incomplete": ("Incomplete", "A selling price is needed before a verdict can be given."),
    }
    v_title, v_line = verdict_copy.get(res["verdict"], ("Reviewed", ""))

    cost_rows = [
        ("Supplier price per unit", res["unit_cost_gbp"], "As quoted, converted to sterling."),
        ("Freight per unit", res["freight_unit"], "Shipment freight divided across the order."),
        ("Insurance per unit", res["insurance_unit"], "Cargo insurance apportioned per unit."),
        ("Duty per unit", res["duty_unit"],
         "%.1f%% charged on goods plus freight and insurance." % inputs["duty_pct"]),
    ]
    if not res["import_vat_reclaimable"]:
        cost_rows.append(("Import VAT per unit", res["import_vat_unit"],
                          "Not reclaimable, so a genuine cost to you."))
    cost_rows.append(("Other costs per unit", res["other_unit"],
                      "Inspection, prep, labelling and tooling."))

    sell_rows = []
    if res["price"] > 0:
        sell_rows = [
            ("Selling price", res["price"], "What the customer pays, VAT included."),
            ("VAT to HMRC", -res["vat_due"],
             "Collected on the sale and passed on." if inputs["vat_registered"] else "Not applicable."),
            ("Amazon referral fee", -res["referral_fee"],
             "%.1f%% of the gross selling price." % inputs["referral_pct"]),
            ("FBA fulfilment fee", -res["fba_fee"], "Pick, pack and delivery, per unit."),
            ("Advertising, storage, returns", -res["other_selling_per_unit"], "Your allowance."),
            ("Landed cost", -res["landed_unit"], "From the table above."),
        ]

    def rows_html(rows):
        out = []
        for label, val, note in rows:
            cls = "neg" if val < 0 else ""
            out.append(
                "<tr><td>%s<span class='note'>%s</span></td><td class='num %s'>%s</td></tr>"
                % (_esc(label), _esc(note), cls, _m(val)))
        return "".join(out)

    scen_html = "".join(
        "<tr class='%s'><td>%s<span class='note'>%s</span></td>"
        "<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
        "<td class='num %s'>%s</td></tr>" % (
            "base" if s["delta"] == 0 else "",
            _esc(s["label"]), _esc(s["note"]), _m(s["profit"]), _pct(s["margin"]),
            "%.0f%%" % s["roi"],
            "neg" if s["delta"] < 0 else "",
            "&mdash;" if s["delta"] == 0 else _m(s["delta"]))
        for s in scen)

    ladder_html = "".join(
        "<tr class='%s'><td class='num'>%s</td><td class='num %s'>%s</td>"
        "<td class='num'>%s</td><td class='num'>%s</td></tr>" % (
            "base" if r["current"] else "", _m(r["price"]),
            "neg" if r["profit"] < 0 else "", _m(r["profit"]),
            _pct(r["margin"]), "%.0f%%" % r["roi"])
        for r in ladder)

    flags_html = "".join("<li>%s</li>" % _esc(f) for f in res["flags"]) or \
        "<li>No structural issues were flagged by the model.</li>"

    recs_html = "".join(
        "<div class='rec'><h4>%d. %s</h4><p>%s</p></div>" % (n, _esc(t), b)
        for n, (t, b) in enumerate(recs, 1))

    q_rows = ""
    q_fields = [
        ("Product", "product_name"), ("Category", "category"),
        ("Target selling price", "target_price"), ("Supplier", "supplier_name"),
        ("Supplier location", "supplier_location"), ("Quoted unit price", "supplier_price"),
        ("Minimum order quantity", "moq"), ("Samples received", "samples"),
        ("Private label required", "private_label"), ("Packaging requirements", "packaging"),
        ("Certifications needed", "certifications"), ("Target launch date", "launch_date"),
        ("Biggest concern", "concerns"),
    ]
    for label, key in q_fields:
        val = (q.get(key) or "").strip()
        if val:
            q_rows += "<tr><th>%s</th><td>%s</td></tr>" % (_esc(label), _esc(val))
    q_block = ("<table class='kv'>%s</table>" % q_rows) if q_rows else \
        "<p class='muted'>No questionnaire responses were supplied.</p>"

    manual_note = ""
    if order and order["report_notes"]:
        manual_note = (
            "<section><h2>Specialist review</h2><div class='manual'>%s</div></section>"
            % _esc(order["report_notes"]))

    ref = order["reference"] if order else "PREVIEW"
    price_block = ""
    if res["price"] > 0:
        price_block = """
        <div class="kpi"><span>Profit per unit</span><strong class="%s">%s</strong></div>
        <div class="kpi"><span>Net margin</span><strong>%s</strong></div>
        <div class="kpi"><span>Return on investment</span><strong>%.0f%%</strong></div>
        """ % ("neg" if res["profit_unit"] < 0 else "", _m(res["profit_unit"]),
               _pct(res["margin_pct"]), res["roi_pct"])

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(config.AUDIT_NAME)} &ndash; {html.escape(product)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{ --ink:#0d1b2a; --paper:#fbfaf7; --rule:#d9d3c7; --amber:#c2703d; --muted:#6b7280; --neg:#a4341f; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink);
  font-family:'Source Serif 4',Georgia,serif; font-size:15px; line-height:1.6; }}
.sheet {{ max-width:860px; margin:0 auto; padding:56px 48px 80px; background:#fff;
  box-shadow:0 1px 40px rgba(13,27,42,.07); }}
h1,h2,h3,h4 {{ font-family:'Archivo',system-ui,sans-serif; letter-spacing:-.01em; }}
.masthead {{ border-bottom:3px solid var(--ink); padding-bottom:18px; margin-bottom:6px;
  display:flex; justify-content:space-between; align-items:flex-end; gap:20px; flex-wrap:wrap; }}
.brand {{ font-family:'Archivo',sans-serif; font-weight:700; font-size:19px; letter-spacing:-.02em; }}
.brand span {{ display:block; font-weight:500; font-size:11px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--amber); margin-top:3px; }}
.meta {{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--muted); text-align:right; }}
h1 {{ font-size:30px; margin:26px 0 4px; font-weight:700; }}
.sub {{ color:var(--muted); font-size:15px; margin:0 0 26px; }}
.verdict {{ border:1px solid var(--rule); border-left:5px solid var(--amber);
  background:#fdfbf8; padding:18px 22px; margin:0 0 26px; }}
.verdict h3 {{ margin:0 0 4px; font-size:17px; }}
.verdict p {{ margin:0; color:#3c4655; }}
.kpis {{ display:flex; flex-wrap:wrap; gap:10px; margin:0 0 30px; }}
.kpi {{ flex:1 1 150px; border:1px solid var(--rule); padding:12px 14px; background:#fdfdfc; }}
.kpi span {{ display:block; font-family:'Archivo',sans-serif; font-size:10px;
  letter-spacing:.1em; text-transform:uppercase; color:var(--muted); margin-bottom:5px; }}
.kpi strong {{ font-family:'IBM Plex Mono',monospace; font-size:19px; font-weight:500; }}
section {{ margin:0 0 34px; }}
h2 {{ font-size:12px; letter-spacing:.16em; text-transform:uppercase; color:var(--amber);
  border-bottom:1px solid var(--rule); padding-bottom:7px; margin:0 0 16px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th, td {{ text-align:left; padding:9px 8px; border-bottom:1px solid #ece8e0; vertical-align:top; }}
thead th {{ font-family:'Archivo',sans-serif; font-size:10px; letter-spacing:.09em;
  text-transform:uppercase; color:var(--muted); border-bottom:1px solid var(--rule); }}
td.num, th.num {{ text-align:right; font-family:'IBM Plex Mono',monospace; white-space:nowrap; }}
.note {{ display:block; font-size:12px; color:var(--muted); line-height:1.45; margin-top:2px; }}
.total td {{ border-top:2px solid var(--ink); border-bottom:none; font-weight:600;
  padding-top:11px; font-size:15px; }}
tr.base {{ background:#fdf6ef; }}
.neg {{ color:var(--neg); }}
.rec {{ margin:0 0 16px; padding-left:15px; border-left:2px solid var(--rule); }}
.rec h4 {{ margin:0 0 3px; font-size:15px; }}
.rec p {{ margin:0; color:#3c4655; }}
ul {{ margin:0; padding-left:19px; }} li {{ margin-bottom:7px; }}
.kv th {{ width:38%; font-family:'Archivo',sans-serif; font-size:12px; color:var(--muted);
  font-weight:500; text-transform:uppercase; letter-spacing:.05em; }}
.muted {{ color:var(--muted); }}
.manual {{ background:#fdf6ef; border:1px solid var(--rule); padding:16px 18px; }}
.cta {{ border:1px solid var(--ink); padding:22px 24px; background:var(--ink); color:#f3efe7; }}
.cta h3 {{ margin:0 0 8px; color:#fff; font-size:17px; }}
.cta p {{ margin:0 0 6px; color:#c9d1dc; font-size:14px; }}
footer {{ margin-top:42px; padding-top:16px; border-top:1px solid var(--rule);
  font-size:11.5px; color:var(--muted); font-family:'Archivo',sans-serif; line-height:1.6; }}
@media print {{
  body {{ background:#fff; }} .sheet {{ box-shadow:none; max-width:none; padding:0 12mm; }}
  section {{ page-break-inside:avoid; }} @page {{ margin:14mm; }}
}}
@media (max-width:640px) {{ .sheet {{ padding:30px 20px 50px; }} h1 {{ font-size:24px; }} }}
</style></head><body><div class="sheet">

<div class="masthead">
  <div class="brand">{html.escape(config.BRAND_NAME)}<span>{html.escape(config.AUDIT_NAME)}</span></div>
  <div class="meta">REF {html.escape(ref)}<br>{generated}<br>Prepared for {html.escape(client)}</div>
</div>

<h1>{html.escape(product)}</h1>
<p class="sub">Landed cost, margin and sourcing assessment for import from China to Amazon UK.</p>

<div class="verdict"><h3>{html.escape(v_title)}</h3><p>{html.escape(v_line)}</p></div>

<div class="kpis">
  <div class="kpi"><span>Landed per unit</span><strong>{_m(res['landed_unit'])}</strong></div>
  <div class="kpi"><span>Break-even price</span><strong>{_m(res['break_even'])}</strong></div>
  {price_block}
</div>

<section><h2>How the landed cost is built</h2>
<table><thead><tr><th>Component</th><th class="num">Per unit</th></tr></thead>
<tbody>{rows_html(cost_rows)}
<tr class="total"><td>Landed cost per unit</td><td class="num">{_m(res['landed_unit'])}</td></tr>
<tr class="total"><td>Total for {int(res['qty'])} units</td><td class="num">{_m(res['landed_total'])}</td></tr>
</tbody></table>
<p class="note" style="margin-top:10px">Cash required before the first sale, including
{'reclaimable import VAT you must still fund' if res['import_vat_reclaimable'] else 'import VAT'}:
<strong>{_m(res['cash_out'])}</strong>. This is the number that catches sellers out, because
Amazon settles on a two-week cycle while the factory wants its balance before shipping.</p>
</section>

{"<section><h2>Where the money goes on each sale</h2><table><thead><tr><th>Line</th><th class='num'>Per unit</th></tr></thead><tbody>" + rows_html(sell_rows) + "<tr class='total'><td>Profit per unit</td><td class='num " + ("neg" if res["profit_unit"] < 0 else "") + "'>" + _m(res["profit_unit"]) + "</td></tr></tbody></table></section>" if sell_rows else ""}

<section><h2>Pricing positions</h2>
<p class="muted" style="margin-top:-6px">Break-even is {_m(res['break_even'])}. To hit a
{res['target_margin_pct']:.0f}% net margin you need {_m(res['target_price'])}; to hit
{res['target_roi_pct']:.0f}% return on investment you need {_m(res['roi_price'])}. We would
aim at <strong>{_m(res['recommended_price'])}</strong> or above.</p>
<table><thead><tr><th class="num">Price</th><th class="num">Profit</th>
<th class="num">Margin</th><th class="num">ROI</th></tr></thead>
<tbody>{ladder_html or "<tr><td colspan='4' class='muted'>Add a selling price to model this.</td></tr>"}</tbody></table>
</section>

<section><h2>What happens when things move against you</h2>
<table><thead><tr><th>Scenario</th><th class="num">Profit</th><th class="num">Margin</th>
<th class="num">ROI</th><th class="num">Change</th></tr></thead>
<tbody>{scen_html}</tbody></table>
<p class="note" style="margin-top:10px">None of these are unusual. A product that only works
in the baseline row is a product that has not been costed with enough room.</p>
</section>

<section><h2>Risk register</h2><ul>{flags_html}</ul></section>

<section><h2>What we would do next</h2>{recs_html}</section>

<section><h2>Your submission</h2>{q_block}</section>

{manual_note}

<section><h2>Taking this further</h2>
<div class="cta"><h3>{html.escape(config.STARTER_NAME)} &nbsp;&middot;&nbsp; {html.escape(config.LAUNCH_NAME)}</h3>
<p>Everything above is modelled from the figures you supplied. The single biggest
improvement available to you is replacing those assumptions with real quotes, and that
is what our China supplier network is for.</p>
<p><strong>{html.escape(config.STARTER_NAME)}, {_m(config.STARTER_PRICE_GBP)}.</strong>
We source three verified factories for this product, confirm they are manufacturers
rather than resellers, negotiate on your behalf and quote the freight properly.</p>
<p><strong>{html.escape(config.LAUNCH_NAME)}, {_m(config.LAUNCH_PRICE_FROM)} to
{_m(config.LAUNCH_PRICE_TO)} by scope.</strong> Everything above plus sample management,
private label and packaging, pre-shipment quality inspection, shipping, import and
customs, FNSKU labelling and prep, and delivery direct into your Amazon FBA warehouse.</p>
<p>{"Message us on WhatsApp on +" + html.escape(config.WHATSAPP_NUMBER) + ", or reply" if config.WHATSAPP_NUMBER else "Reply"}
to your confirmation email and we will come back with sourcing options for this product.</p>
</div></section>

<footer>
Prepared by {html.escape(config.BRAND_NAME)}. This report is a commercial assessment based on
figures supplied by the client and current published Amazon fee structures. Duty rates and
commodity codes should be confirmed with HMRC or a customs broker before goods are ordered.
It is not tax, legal or financial advice.
</footer>
</div></body></html>"""


def build_for_order(order, lead):
    """Rebuild an order's report from stored inputs. Safe to call repeatedly."""
    res_raw = json.loads(lead["calc_results"]) if lead and lead["calc_results"] else None
    q = json.loads(order["questionnaire"]) if order and order["questionnaire"] else {}
    if not res_raw:
        return "<p>No calculator data is stored against this order.</p>"
    # Recalculate so a report always reflects the current engine, and so any
    # questionnaire correction to price or quantity is picked up.
    inputs = dict(res_raw["inputs"])
    for key, field in (("target_price", "selling_price"), ("supplier_price", "unit_cost"),
                       ("moq", "quantity")):
        val = (q.get(key) or "").strip() if q else ""
        if val:
            from calc import _f
            parsed = _f(val, 0)
            if parsed > 0:
                inputs[field] = parsed
    res = calculate(Inputs(**inputs))
    return build_report(order, lead, res, q)
