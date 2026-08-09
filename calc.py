"""Landed cost and profit engine for UK importers selling on Amazon.

The two things most calculators get wrong, and which are handled properly here:

1. Import VAT is charged on (goods + freight + duty), but a VAT-registered
   seller reclaims it. For them it is a cash-flow event, not a cost. Treating
   it as a cost understates margin by roughly a fifth.
2. Amazon's referral fee is taken on the full VAT-inclusive price the customer
   pays, while a VAT-registered seller only keeps price / 1.2 as revenue.
   Charging the referral on the net figure flatters the result.
"""
from dataclasses import dataclass, asdict, field


def _f(value, default=0.0):
    """Tolerant float parse: blank, None and junk all collapse to a default."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().replace(",", "").replace("£", "").replace("$", "")
    if not cleaned:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


@dataclass
class Inputs:
    product_name: str = ""
    quantity: float = 100.0
    unit_cost: float = 0.0            # per unit, supplier price
    cost_currency: str = "GBP"        # GBP or USD
    fx_usd_gbp: float = 0.79
    freight_total: float = 0.0        # total freight for the whole shipment
    freight_currency: str = "GBP"
    insurance_total: float = 0.0
    duty_pct: float = 4.7
    vat_rate: float = 20.0
    vat_registered: bool = True
    other_costs_total: float = 0.0    # inspection, prep, labelling, tooling
    referral_pct: float = 15.0
    fba_fee: float = 0.0              # per unit
    other_selling_per_unit: float = 0.0   # storage, returns provision, ads
    selling_price: float = 0.0        # VAT-inclusive price the buyer pays

    @classmethod
    def from_form(cls, form):
        get = form.get
        return cls(
            product_name=(get("product_name") or "").strip()[:200],
            quantity=max(1.0, _f(get("quantity"), 100)),
            unit_cost=max(0.0, _f(get("unit_cost"))),
            cost_currency="USD" if (get("cost_currency") or "GBP").upper() == "USD" else "GBP",
            fx_usd_gbp=max(0.0001, _f(get("fx_usd_gbp"), 0.79)),
            freight_total=max(0.0, _f(get("freight_total"))),
            freight_currency="USD" if (get("freight_currency") or "GBP").upper() == "USD" else "GBP",
            insurance_total=max(0.0, _f(get("insurance_total"))),
            duty_pct=max(0.0, _f(get("duty_pct"), 4.7)),
            vat_rate=max(0.0, _f(get("vat_rate"), 20)),
            vat_registered=str(get("vat_registered", "yes")).lower() in ("yes", "true", "1", "on"),
            other_costs_total=max(0.0, _f(get("other_costs_total"))),
            referral_pct=max(0.0, _f(get("referral_pct"), 15)),
            fba_fee=max(0.0, _f(get("fba_fee"))),
            other_selling_per_unit=max(0.0, _f(get("other_selling_per_unit"))),
            selling_price=max(0.0, _f(get("selling_price"))),
        )


def calculate(i: Inputs) -> dict:
    qty = max(1.0, i.quantity)
    v = i.vat_rate / 100.0
    r = i.referral_pct / 100.0

    # --- Convert everything to GBP -----------------------------------------
    unit_cost = i.unit_cost * (i.fx_usd_gbp if i.cost_currency == "USD" else 1.0)
    freight_total = i.freight_total * (i.fx_usd_gbp if i.freight_currency == "USD" else 1.0)

    goods_total = unit_cost * qty
    freight_unit = freight_total / qty
    insurance_unit = i.insurance_total / qty
    other_unit = i.other_costs_total / qty

    # --- Import charges -----------------------------------------------------
    # Duty is levied on the CIF value: goods + freight + insurance.
    cif_unit = unit_cost + freight_unit + insurance_unit
    duty_unit = cif_unit * (i.duty_pct / 100.0)
    # Import VAT sits on top of CIF + duty.
    import_vat_unit = (cif_unit + duty_unit) * v
    # Reclaimable when VAT registered, so it does not belong in the cost base.
    import_vat_cost = 0.0 if i.vat_registered else import_vat_unit

    landed_unit = cif_unit + duty_unit + import_vat_cost + other_unit
    landed_total = landed_unit * qty

    # --- Selling side -------------------------------------------------------
    price = i.selling_price
    net_revenue = price / (1 + v) if i.vat_registered else price
    vat_due = price - net_revenue
    referral_fee = price * r          # Amazon takes its cut of the gross price
    amazon_fees = referral_fee + i.fba_fee
    selling_costs = amazon_fees + i.other_selling_per_unit

    profit_unit = net_revenue - selling_costs - landed_unit
    margin_pct = (profit_unit / net_revenue * 100.0) if net_revenue > 0 else 0.0
    roi_pct = (profit_unit / landed_unit * 100.0) if landed_unit > 0 else 0.0
    profit_total = profit_unit * qty

    # --- Break-even ---------------------------------------------------------
    # Solve for P where net(P) - referral(P) - fixed = 0.
    #   P/(1+v) - rP = fba + other_selling + landed      (VAT registered)
    #   P - rP       = fba + other_selling + landed      (not registered)
    fixed = i.fba_fee + i.other_selling_per_unit + landed_unit
    coeff = (1 / (1 + v) if i.vat_registered else 1.0) - r
    break_even = fixed / coeff if coeff > 0 else 0.0

    # Price needed to hit the target margin: margin = profit / net_revenue
    #   P/(1+v)*(1-m) - rP = fixed
    def price_for_margin(m_pct):
        m = m_pct / 100.0
        c = (1 / (1 + v) if i.vat_registered else 1.0) * (1 - m) - r
        return fixed / c if c > 0 else 0.0

    def price_for_roi(roi_pct_target):
        # profit = landed * roi  ->  net - referral - fixed = landed * roi
        target_profit = landed_unit * (roi_pct_target / 100.0)
        c = (1 / (1 + v) if i.vat_registered else 1.0) - r
        return (fixed + target_profit) / c if c > 0 else 0.0

    from config import TARGET_MARGIN_PCT, TARGET_ROI_PCT
    target_price = price_for_margin(TARGET_MARGIN_PCT)
    roi_price = price_for_roi(TARGET_ROI_PCT)
    recommended_price = max(target_price, roi_price)

    # --- Cash position ------------------------------------------------------
    cash_out = landed_total + (import_vat_unit * qty if i.vat_registered else 0.0)
    units_to_recover = (landed_total / profit_unit) if profit_unit > 0 else None

    verdict, verdict_note = _verdict(margin_pct, roi_pct, profit_unit, price)

    return {
        "inputs": asdict(i),
        "qty": qty,
        "unit_cost_gbp": unit_cost,
        "goods_total": goods_total,
        "freight_unit": freight_unit,
        "insurance_unit": insurance_unit,
        "other_unit": other_unit,
        "cif_unit": cif_unit,
        "duty_unit": duty_unit,
        "import_vat_unit": import_vat_unit,
        "import_vat_reclaimable": i.vat_registered,
        "landed_unit": landed_unit,
        "landed_total": landed_total,
        "price": price,
        "net_revenue": net_revenue,
        "vat_due": vat_due,
        "referral_fee": referral_fee,
        "fba_fee": i.fba_fee,
        "amazon_fees": amazon_fees,
        "other_selling_per_unit": i.other_selling_per_unit,
        "selling_costs": selling_costs,
        "profit_unit": profit_unit,
        "profit_total": profit_total,
        "margin_pct": margin_pct,
        "roi_pct": roi_pct,
        "break_even": break_even,
        "target_margin_pct": TARGET_MARGIN_PCT,
        "target_price": target_price,
        "target_roi_pct": TARGET_ROI_PCT,
        "roi_price": roi_price,
        "recommended_price": recommended_price,
        "cash_out": cash_out,
        "units_to_recover": units_to_recover,
        "verdict": verdict,
        "verdict_note": verdict_note,
        "flags": _flags(i, landed_unit, margin_pct, roi_pct, price, break_even),
    }


def _verdict(margin_pct, roi_pct, profit_unit, price):
    if price <= 0:
        return "incomplete", "Add a selling price to see profit and margin."
    if profit_unit <= 0:
        return "loss", "At this price the product loses money on every unit sold."
    if margin_pct < 10 or roi_pct < 30:
        return "thin", "The numbers work, but there is almost no room for error here."
    if margin_pct < 20 or roi_pct < 70:
        return "workable", "Viable, though tighter than most sellers plan for."
    return "strong", "These are healthy numbers for an FBA product."


def _flags(i: Inputs, landed_unit, margin_pct, roi_pct, price, break_even):
    """Plain-English warnings. This is the part sellers actually learn from."""
    out = []
    if not i.vat_registered and price > 0:
        out.append(
            "You are not VAT registered, so the import VAT you pay at the border "
            "is a real cost and cannot be reclaimed. Registering usually changes "
            "the picture significantly once volume builds."
        )
    if i.vat_registered:
        out.append(
            "Import VAT is reclaimable for you, so it is excluded from cost, but "
            "you still fund it up front. Budget it as cash, not profit."
        )
    if i.freight_total <= 0:
        out.append("No freight entered. Shipping from China is rarely free, and it is "
                   "the cost that most often turns a good margin into a bad one.")
    if i.duty_pct <= 0:
        out.append("Duty is set to zero. Very few goods enter the UK duty free, so "
                   "confirm the commodity code before you commit to an order.")
    if i.fba_fee <= 0:
        out.append("No FBA fulfilment fee entered. Amazon charges this on every unit "
                   "and it is frequently larger than sellers expect.")
    if i.other_selling_per_unit <= 0:
        out.append("Nothing allowed for advertising, returns or storage. Almost no "
                   "new listing sells without ad spend.")
    if price > 0 and break_even > 0 and price < break_even * 1.15:
        out.append("Your selling price sits close to break-even. A small fee change "
                   "or a discount would push this product into a loss.")
    if margin_pct >= 45 and price > 0:
        out.append("The margin looks unusually high. Double check the FBA fee and "
                   "referral percentage for your category before relying on it.")
    if i.quantity < 50:
        out.append("Small order quantity. Per-unit freight and setup costs fall "
                   "sharply with volume, so this understates what is achievable.")
    return out


def summarise(res: dict) -> str:
    """One-line plain text summary used in emails and the admin list."""
    if res["price"] <= 0:
        return "Landed cost £%.2f per unit, no selling price supplied." % res["landed_unit"]
    return "Landed £%.2f, sells £%.2f, profit £%.2f per unit (%.1f%% margin, %.0f%% ROI)." % (
        res["landed_unit"], res["price"], res["profit_unit"], res["margin_pct"], res["roi_pct"],
    )
