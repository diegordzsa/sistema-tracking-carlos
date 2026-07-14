"""Test Shopify connection: auth, fetch orders, inspect UTM and payment data."""
import json
from datetime import datetime, timedelta

import config
import shopify_client


def main():
    config.validate_config()
    print("Testing Shopify connection...\n")

    print("1. Authenticating...")
    token = shopify_client._get_access_token()
    print(f"   Token obtained: {token[:10]}...\n")

    print("2. Fetching recent orders (last 7 days)...")
    now = datetime.now(config.TIMEZONE)
    start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0).isoformat()
    end = now.isoformat()

    orders = shopify_client.fetch_orders(start, end)
    print(f"   Total orders: {len(orders)}\n")

    if not orders:
        print("   No orders found in the last 7 days.")
        return

    print("3. Inspecting payment gateways (for COD detection)...")
    gateways = set()
    for o in orders:
        for gw in o.get("payment_gateway_names", []):
            gateways.add(gw)
    print(f"   Unique gateways: {gateways}\n")

    print("4. Inspecting UTM data (landing_site)...")
    carlos_orders = []
    for o in orders:
        landing = o.get("landing_site", "")
        if landing:
            is_carlos = shopify_client.is_carlos_order(o)
            medium = shopify_client.get_utm_medium(o)
            print(f"   {o.get('name', '?')}: landing={landing[:80]} | carlos={is_carlos} | medium={medium}")
            if is_carlos:
                carlos_orders.append(o)

    print(f"\n   Carlos-attributed orders: {len(carlos_orders)}\n")

    print("5. Inspecting fulfillment data...")
    for o in orders[:5]:
        fi = shopify_client.get_fulfillment_info(o)
        payment_type = shopify_client.classify_payment_type(o)
        print(f"   {o.get('name', '?')}: type={payment_type} | fulfillment={fi['fulfillment_status']} | shipment={fi['shipment_status']} | courier={fi['tracking_company']}")

    print("\n6. Sample order record...")
    sample = shopify_client.build_order_record(orders[0])
    print(json.dumps(sample, indent=2, ensure_ascii=False))

    print("\nDone. Connection working correctly.")


if __name__ == "__main__":
    main()
