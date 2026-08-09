"""Central configuration. Everything brandable or chargeable lives here."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"
DATA_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)


def _env(key, default=""):
    return os.environ.get(key, default)


def _flag(key, default=False):
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# --- Brand -----------------------------------------------------------------
BRAND_NAME = _env("BRAND_NAME", "Harbourline Sourcing")
BRAND_TAGLINE = _env("BRAND_TAGLINE", "China sourcing and Amazon FBA delivery for UK sellers")
BRAND_DOMAIN = _env("BRAND_DOMAIN", "")          # e.g. harbourlinesourcing.co.uk
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "http://167.99.198.145:8110").rstrip("/")
CONTACT_EMAIL = _env("CONTACT_EMAIL", "")         # shown on site only if set
CONTACT_PHONE = _env("CONTACT_PHONE", "")

# --- Pricing ---------------------------------------------------------------
AUDIT_PRICE_GBP = float(_env("AUDIT_PRICE_GBP", "79"))
AUDIT_NAME = _env("AUDIT_NAME", "Product Profit Audit")
PREMIUM_PRICE_GBP = float(_env("PREMIUM_PRICE_GBP", "499"))
PREMIUM_NAME = _env("PREMIUM_NAME", "Full Sourcing & FBA Launch")

# --- Calculator defaults (UK) ---------------------------------------------
DEFAULT_VAT_RATE = 20.0
DEFAULT_REFERRAL_PCT = 15.0
DEFAULT_DUTY_PCT = 4.7
DEFAULT_FX_USD_GBP = float(_env("FX_USD_GBP", "0.79"))
TARGET_MARGIN_PCT = float(_env("TARGET_MARGIN_PCT", "25"))
TARGET_ROI_PCT = float(_env("TARGET_ROI_PCT", "100"))

# --- Payments --------------------------------------------------------------
# Leave keys blank to run in DEMO mode: the payment step is simulated end-to-end
# so the whole funnel can be tested before any gateway account exists.
STRIPE_SECRET_KEY = _env("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = _env("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = _env("STRIPE_WEBHOOK_SECRET")
PAYPAL_CLIENT_ID = _env("PAYPAL_CLIENT_ID")
PAYPAL_SECRET = _env("PAYPAL_SECRET")
PAYPAL_LIVE = _flag("PAYPAL_LIVE", False)

PAYMENTS_LIVE = bool(STRIPE_SECRET_KEY) or bool(PAYPAL_CLIENT_ID)

# --- Email -----------------------------------------------------------------
# With no SMTP host configured every message is still composed and stored in the
# outbox so it can be read in the admin area. Nothing is silently dropped.
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASS = _env("SMTP_PASS")
SMTP_FROM = _env("SMTP_FROM", "")
SMTP_TLS = _flag("SMTP_TLS", True)
ADMIN_NOTIFY_EMAIL = _env("ADMIN_NOTIFY_EMAIL", "")
EMAIL_LIVE = bool(SMTP_HOST and SMTP_FROM)

# --- Admin -----------------------------------------------------------------
ADMIN_USER = _env("ADMIN_USER", "admin")
ADMIN_PASS = _env("ADMIN_PASS", "harbourline2026")
SESSION_SECRET = _env("SESSION_SECRET", "change-this-secret-in-production-please")

DB_PATH = str(DATA_DIR / "app.db")

# --- Service catalogue (drives the services section) -----------------------
SOURCING_SERVICES = [
    ("Product sourcing", "We find and shortlist factories for your product, not trading-company middlemen."),
    ("Factory communication", "All negotiation handled in Mandarin, in your interest, with specs written down."),
    ("Bulk purchasing", "Our combined order volume gets you pricing a first-time buyer cannot ask for."),
    ("Quality checks", "Pre-shipment inspection against an agreed checklist, with photographs."),
    ("Competitive pricing", "Multiple quotes per product so you see the real market, not one number."),
    ("Shipping solutions", "Sea, rail or air compared on landed cost and lead time, then booked."),
    ("Import support", "Commodity codes, duty rates, customs paperwork and VAT handled properly."),
    ("Direct delivery to Amazon FBA", "Goods delivered into your FBA warehouse, not to your garage."),
    ("FBA prep and labelling", "FNSKU labelling, polybagging and carton marking done to Amazon spec."),
    ("Private label solutions", "Your brand on the product, with tooling and MOQ negotiated for you."),
    ("Packaging and custom branding", "Boxes, inserts and manuals designed and produced at source."),
]
