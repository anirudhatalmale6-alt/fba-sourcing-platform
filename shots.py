import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8899"
OUT = "/var/lib/freelancer/projects/40416335/fba-platform/shots"
import os
os.makedirs(OUT, exist_ok=True)

FIG = {
    "product_name": "Stainless steel dog bowl 18cm", "quantity": "500", "unit_cost": "2.10",
    "freight_total": "620", "other_costs_total": "150", "selling_price": "14.99",
    "fba_fee": "2.85", "other_selling_per_unit": "1.50",
}

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 800})

    pg.goto(BASE + "/", wait_until="networkidle")
    pg.screenshot(path=f"{OUT}/01-home-hero.png")

    pg.goto(BASE + "/#calculator", wait_until="networkidle")
    pg.wait_for_timeout(400)
    for k, v in FIG.items():
        try:
            pg.fill(f"#calcform [name='{k}']", v)
        except Exception:
            pass
    pg.screenshot(path=f"{OUT}/02-calculator-form.png")
    pg.click("#calcform button[type=submit]")
    pg.wait_for_selector("#gateform", timeout=8000)
    pg.wait_for_timeout(400)
    pg.screenshot(path=f"{OUT}/03-results-gated.png")

    pg.fill("#gateform [name='name']", "Jane Smith")
    pg.fill("#gateform [name='email']", "jane@example.co.uk")
    pg.fill("#gateform [name='product_name']", "Stainless steel dog bowl 18cm")
    pg.fill("#gateform [name='supplier_details']", "Ningbo supplier, $2.10 at 500 MOQ")
    pg.click("#gateform button[type=submit]")
    pg.wait_for_timeout(1800)
    pg.evaluate("document.querySelector('#results').scrollIntoView()")
    pg.wait_for_timeout(300)
    pg.screenshot(path=f"{OUT}/04-results-unlocked.png")

    # pricing + services
    pg.goto(BASE + "/#pricing", wait_until="networkidle")
    pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/05-pricing.png")
    pg.goto(BASE + "/services", wait_until="networkidle")
    pg.evaluate("window.scrollTo(0, 620)")
    pg.wait_for_timeout(350)
    pg.screenshot(path=f"{OUT}/06-services.png")

    # audit page
    pg.goto(BASE + "/audit", wait_until="networkidle")
    pg.screenshot(path=f"{OUT}/07-audit.png")

    # report: use the newest paid order token from admin
    pg.goto(BASE + "/admin/login", wait_until="networkidle")
    pg.fill("[name='username']", "admin")
    pg.fill("[name='password']", "harbourline2026")
    pg.click("button[type=submit]")
    pg.wait_for_timeout(700)
    pg.screenshot(path=f"{OUT}/08-admin-dashboard.png")

    pg.goto(BASE + "/admin/orders", wait_until="networkidle")
    href = pg.eval_on_selector("table.data a", "a => a.getAttribute('href')")
    pg.goto(BASE + href, wait_until="networkidle")
    pg.screenshot(path=f"{OUT}/09-admin-order.png")
    tok = pg.eval_on_selector("a[href^='/report/']", "a => a.getAttribute('href')")

    pg.goto(BASE + tok, wait_until="networkidle")
    pg.wait_for_timeout(600)
    pg.screenshot(path=f"{OUT}/10-report-top.png")
    for i, y in enumerate([760, 1560, 2360, 3160], start=11):
        pg.evaluate(f"window.scrollTo(0,{y})")
        pg.wait_for_timeout(320)
        pg.screenshot(path=f"{OUT}/{i}-report-{y}.png")

    # mobile
    m = b.new_page(viewport={"width": 390, "height": 780})
    m.goto(BASE + "/", wait_until="networkidle")
    m.screenshot(path=f"{OUT}/15-mobile-home.png")
    m.goto(BASE + "/#calculator", wait_until="networkidle")
    m.wait_for_timeout(400)
    m.screenshot(path=f"{OUT}/16-mobile-calc.png")

    b.close()
print("shots done")
