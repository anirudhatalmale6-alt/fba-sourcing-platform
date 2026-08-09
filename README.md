# Amazon FBA Landed Cost Platform

A lead-generation funnel for a China sourcing and Amazon FBA business. A free landed-cost
calculator brings sellers in, captures them as leads, sells an automated Product Profit Audit,
and positions the full sourcing service behind it.

```
Calculator  ->  Lead capture  ->  Paid audit  ->  Questionnaire  ->  Report  ->  Sourcing service
   free         email + data      Stripe/PayPal    product detail    auto + manual    the real revenue
                      |
                      +--> 3-step follow-up sequence (stops on purchase or unsubscribe)
```

Three tiers: the audit is bought online, the two sourcing packages are enquiry-led because
they need a conversation before anyone should be taking money.

| Tier | Price | Sold by |
|---|---|---|
| Automated Amazon Profit Audit | £79 | Checkout |
| Sourcing Starter Package | £499 | Enquiry |
| Full FBA Launch Package | £1,500–£3,000 | Enquiry |

## What is included

| Piece | Detail |
|---|---|
| Calculator | Landed cost, break-even, profit, margin, ROI, cash required. Correct UK import VAT and Amazon referral treatment. |
| Lead capture | Headline figures shown free; profit and margin gated behind name, email, product and supplier details. Emailed summary. |
| Payments | Stripe Checkout and PayPal Orders v2, both over the standard library. Demo mode when no keys are set. |
| Questionnaire | Post-purchase product and supplier detail, feeding the report. |
| Reports | Self-contained HTML audit: cost build-up, pricing ladder, six stress tests, risk register, recommendations. Print-ready. |
| Manual upgrade | A specialist writes their own analysis in admin; it is added to the report and lifts it to the premium tier. |
| Admin | Dashboard, orders, leads, enquiries, email outbox, CSV export, manual payment marking. |
| Emails | Calculator summary, order confirmation, report ready, internal alerts. Stored in an outbox if SMTP is absent. |
| Follow-up sequence | Three automated emails after the calculator: hidden Amazon costs, the China sourcing advantage, then the audit offer. Personalised with the lead's own figures. Cancels itself on purchase or unsubscribe. |
| WhatsApp | Floating button, nav link and inline panels on the pages where people hesitate. Renders only when a number is configured. |

## Running it

```bash
pip3 install fastapi uvicorn jinja2 python-multipart
python3 -m uvicorn main:app --host 0.0.0.0 --port 8110
```

Nothing else is required. Storage is SQLite in `data/app.db`, created on first run.

## Configuration

All settings are environment variables, read in `config.py`. Nothing is hard-coded.

| Variable | Purpose |
|---|---|
| `BRAND_NAME`, `BRAND_TAGLINE` | Company name and strapline used across the site, reports and emails. |
| `PUBLIC_BASE_URL` | Public URL. Used in emails and payment return links. Must be correct in production. |
| `AUDIT_PRICE_GBP`, `AUDIT_NAME` | The automated tier. |
| `PREMIUM_PRICE_GBP`, `PREMIUM_NAME` | The manual tier. |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` | Card payments. |
| `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`, `PAYPAL_LIVE` | PayPal. `PAYPAL_LIVE=1` switches off sandbox. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `SMTP_TLS` | Outbound email. |
| `ADMIN_NOTIFY_EMAIL` | Where new lead and sale alerts go. |
| `ADMIN_USER`, `ADMIN_PASS`, `SESSION_SECRET` | Admin access. Change all three before going live. |
| `STARTER_PRICE_GBP`, `STARTER_NAME` | The sourcing tier. |
| `LAUNCH_PRICE_FROM`, `LAUNCH_PRICE_TO`, `LAUNCH_NAME` | The done-for-you tier. |
| `WHATSAPP_NUMBER`, `WHATSAPP_HOURS`, `WHATSAPP_PREFILL` | Digits only, international, no plus sign. Blank hides every WhatsApp element. |
| `SEQ_HIDDEN_COSTS_HOURS`, `SEQ_SOURCING_HOURS`, `SEQ_OFFER_HOURS` | Follow-up timings, default 24 / 72 / 120. Set to fractions to watch the sequence run while testing. |
| `SEQUENCE_ENABLED`, `SEQUENCE_TICK_SECONDS` | Turn the sequence off, or change how often it checks for due mail. |
| `TARGET_MARGIN_PCT`, `TARGET_ROI_PCT` | The benchmarks the calculator recommends against. |
| `FX_USD_GBP` | Default dollar rate shown in the form. |

With no gateway keys the checkout uses a demo step; with no SMTP every email is composed and
stored in the admin outbox instead of being sent. Both are deliberate, so the entire funnel can
be tested before accounts exist. Adding keys removes the demo step automatically.

## Going live on a domain

1. Point an A record at the server.
2. Install the vhost in `deploy/nginx.conf`, replacing `YOUR_DOMAIN`.
3. `certbot --nginx -d YOUR_DOMAIN -d www.YOUR_DOMAIN`
4. Set `PUBLIC_BASE_URL=https://YOUR_DOMAIN` and restart.
5. Add gateway keys and SMTP, then change the admin password.

Stripe webhook endpoint: `POST /webhook/stripe` (event `checkout.session.completed`). The
success URL already settles the order, so the webhook is a safety net for customers who close
the tab during payment.

## The calculation

Two things this gets right that most calculators do not:

1. **Import VAT is reclaimable when VAT registered.** Charged on (goods + freight + insurance +
   duty), but for a registered seller it is cash flow, not cost. Treating it as a cost understates
   margin by roughly a fifth. The calculator asks, and shows the money either way.
2. **Amazon's referral fee is taken on the gross, VAT-inclusive price**, while a registered seller
   only keeps `price / 1.2`. Taking the referral off the net figure flatters the result.

Break-even solves `P/(1+v) - rP = fixed`, where `fixed` is landed cost plus FBA and other per-unit
selling costs. Target-margin and target-ROI prices are solved the same way. `calc.py` carries the
derivations in comments.

## Testing

`e2e_test.py` walks the entire funnel against a running instance and checks 43 behaviours,
including that the profit figures are genuinely gated, the report contains the specialist's notes,
and the admin area rejects anonymous requests.

```bash
python3 e2e_test.py http://127.0.0.1:8110 admin yourpassword
```

## Files

```
main.py         routes: public site, funnel, payments, reports, admin
calc.py         the costing engine, with the derivations
reportgen.py    builds the audit report from inputs plus questionnaire
payments.py     Stripe and PayPal over urllib, plus demo mode
emailer.py      SMTP with an outbox fallback
db.py           SQLite schema and queries
config.py       every setting, all environment driven
templates/      site, funnel and admin views
static/app.css  the design system
deploy/         nginx vhost and systemd unit
```
