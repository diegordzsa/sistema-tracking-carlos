import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

SHOPIFY_STORE_DOMAIN = os.getenv("SHOPIFY_STORE_DOMAIN", "ex9fk2-1i.myshopify.com")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")
SHOPIFY_API_VERSION = "2025-01"

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

ZADARMA_API_KEY = os.getenv("ZADARMA_API_KEY")
ZADARMA_API_SECRET = os.getenv("ZADARMA_API_SECRET")
ZADARMA_SIP = os.getenv("ZADARMA_SIP", "141683")


def has_zadarma() -> bool:
    return bool(ZADARMA_API_KEY and ZADARMA_API_SECRET)

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

TIMEZONE = ZoneInfo("Europe/Madrid")
UTM_SOURCE = "carlos"
CLOSER_NAME = "Carlos"
CLOSER_TAG = os.getenv("CLOSER_TAG", "Closer Andres Contreras")
CURRENCY = "EUR"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ORDERS_LOG = os.path.join(DATA_DIR, "orders_log.jsonl")
CALLS_LOG = os.path.join(DATA_DIR, "calls_log.jsonl")


def validate_config():
    missing = []
    if not SHOPIFY_CLIENT_ID:
        missing.append("SHOPIFY_CLIENT_ID")
    if not SHOPIFY_CLIENT_SECRET:
        missing.append("SHOPIFY_CLIENT_SECRET")
    if not SLACK_WEBHOOK_URL:
        missing.append("SLACK_WEBHOOK_URL")
    if missing:
        raise EnvironmentError(f"Faltan variables en .env: {', '.join(missing)}")


if __name__ == "__main__":
    validate_config()
    print("Configuracion OK")
