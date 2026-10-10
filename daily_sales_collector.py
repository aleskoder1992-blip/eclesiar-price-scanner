import os
import requests
from datetime import datetime, timedelta, timezone

# Configuration
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
API_KEY = os.environ["ECLESIAR_API_KEY"]

ECLESIAR_API = "https://api.eclesiar.com"
COUNTRY_ID = 2
COUNTRY_NAME = "United Kingdom"

# Collect the previous complete UTC calendar day.
yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1))
day_start = datetime.combine(
    yesterday, datetime.min.time(), tzinfo=timezone.utc
)
day_end = day_start + timedelta(days=1)

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {API_KEY}"})

def get_transactions(page):
    response = session.get(
        f"{ECLESIAR_API}/country/currency-transactions",
        params={
            "country_id": COUNTRY_ID,
            "page": page
        },
        timeout=30
    )
    response.raise_for_status()
    return response.json()


def save_to_supabase(records):
    if not records:
        print("No market purchases found for the selected day.")
        return

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/market_sales_history",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal"
        },
        params={
            "on_conflict": "recorded_date,country_id,item_id"
        },
        json=records,
        timeout=60
    )
    response.raise_for_status()
    print(f"Saved {len(records)} item records to Supabase.")


def main():
    sales = {}
    transactions_count = {}
    page = 1
    records_checked = 0
    reached_day_start = False

    while not reached_day_start:
        payload = get_transactions(page)

        if isinstance(payload, dict):
            records = payload.get("data", [])
            print("API payload type:", type(payload).__name__)
            print("API data type and preview:", type(records).__name__, repr(records)[:1000])
            pagination = payload.get("pagination", {})
            total_pages = int(pagination.get("total_pages", 1))

        elif isinstance(payload, list):
            records = payload
            total_pages = 1

        else:
            raise RuntimeError(
                f"Unexpected API response type: {type(payload).__name__}"
            )

        if not records:
            break

        for record in records:
            if not isinstance(record, dict):
                print("Unexpected record type:", type(record).__name__)
                print("Unexpected record value:", repr(record)[:500])
                raise RuntimeError("Unexpected transaction record format")

            timestamp = record.get("created_at")

            if not timestamp:
                continue

            try:
                transaction_time = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                )

                if transaction_time.tzinfo is None:
                    transaction_time = transaction_time.replace(
                        tzinfo=timezone.utc
                    )
            except ValueError:
                continue

            if transaction_time < day_start:
                reached_day_start = True
                break

            if transaction_time >= day_end:
                continue

            if record.get("description") != "Items bought in the market":
                continue

            for complex_transaction in record.get(
                "complex_transactions", []
            ):
                for item_log in complex_transaction.get("item_logs", []):
                    if item_log.get("description") != "Items bought in the market":
                        continue

                    item_id = item_log.get("item_id")
                    quantity = int(item_log.get("quantity", 0))

                    if item_id is None or quantity <= 0:
                        continue

                    sales[item_id] = sales.get(item_id, 0) + quantity
                    transactions_count[item_id] = (
                        transactions_count.get(item_id, 0) + 1
                    )

        records_checked += len(records)
        print(
            f"Checked page {page}/{total_pages}; "
            f"{records_checked} transaction records examined."
        )

        if reached_day_start or page >= total_pages:
            break

        page += 1

    # Retrieve item names and qualities from the Eclesiar API.
    items_response = session.get(
        f"{ECLESIAR_API}/server/items",
        timeout=30
    )
    items_response.raise_for_status()
    items_payload = items_response.json()
    items = (
        items_payload.get("data", [])
        if isinstance(items_payload, dict)
        else items_payload
    )

    item_lookup = {
        int(item["id"]): item
        for item in items
        if item.get("id") is not None
    }

    records = []

    for item_id, quantity in sales.items():
        item = item_lookup.get(int(item_id), {})

        records.append({
            "recorded_date": yesterday.isoformat(),
            "country_id": COUNTRY_ID,
            "country_name": COUNTRY_NAME,
            "item_id": int(item_id),
            "item_name": item.get("name", f"Unknown item ({item_id})"),
            "quality": item.get("quality"),
            "units_purchased": int(quantity),
            "purchase_transactions": int(
                transactions_count[item_id]
            )
        })

    save_to_supabase(records)


if __name__ == "__main__":
    main()
