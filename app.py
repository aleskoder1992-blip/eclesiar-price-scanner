
import os
import time
import requests
import pandas as pd
import streamlit as st

BASE = "https://api.eclesiar.com"
API_KEY = os.getenv("ECLESIAR_API_KEY", "")

st.set_page_config(page_title="Eclesiar Price Scanner", layout="wide")
st.title("Eclesiar Market Price Scanner")
st.caption("Compare the cheapest market offer for an item across all available countries.")

api_key = st.text_input(
    "Eclesiar API key",
    value=API_KEY,
    type="password",
    help="Create/manage your key in Eclesiar Developer Tools. It is used only for this session."
)

if not api_key:
    st.info("Enter your Eclesiar API key to start.")
    st.stop()

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {api_key}"})

@st.cache_data(ttl=300)
def api_get(path, params=None):
    r = session.get(BASE + path, params=params, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code}: {r.text[:500]}")
    payload = r.json()
    return payload.get("data", [])

def save_sales_history(rows, recorded_date, country_id, country_name):
    supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
    supabase_key = st.secrets["SUPABASE_KEY"]

    url = f"{supabase_url}/rest/v1/market_sales_history"

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }

    records = []

    for row in rows:
        records.append({
            "recorded_date": recorded_date,
            "country_id": int(country_id),
            "country_name": country_name,
            "item_id": int(row["item_id"]),
            "item_name": str(row["item_name"]),
            "quality": row["quality"],
            "units_purchased": int(row["units_purchased"]),
            "purchase_transactions": int(row["purchase_transactions"])
        })

    if not records:
        return 0

    response = requests.post(
        url,
        headers=headers,
        params={"on_conflict": "recorded_date,country_id,item_id"},
        json=records,
        timeout=30
    )

    if not response.ok:
        raise RuntimeError(
            f"Supabase save failed ({response.status_code}): "
            f"{response.text}"
        )

    return len(records)

@st.cache_data(ttl=300)
def get_items():
    rows = []
    page = 1
    while True:
        data = api_get("/server/items", {"page": page})
        rows.extend(data)
        if len(data) < 25:
            break
        page += 1
    return rows

@st.cache_data(ttl=300)
def get_countries():
    return api_get("/countries")

def scan_item(item_id, min_qty=1, include_inactive_markets=False):
    countries = get_countries()
    results = []

    progress = st.progress(0)
    status = st.empty()

    for i, country in enumerate(countries, 1):
        if not country.get("is_available", True) and not include_inactive_markets:
            progress.progress(i / len(countries))
            continue

        cid = country["id"]
        status.write(f"Scanning {country['name']} ({i}/{len(countries)})")

        try:
                        # Fetch market offers for this country and item
            offers = api_get("/market/items/get", {
                "country_id": cid,
                "item_id": item_id,
                "page": 1
            })

          
            # API returns cheapest first. Find first offer with enough stock.
            offer = next((x for x in offers if float(x.get("amount", 0)) >= min_qty), None)
            if not offer:
                progress.progress(i / len(countries))
                continue

            currency = offer.get("currency", {})
            import_tax = offer.get("import_tax", {})
            results.append({
                "Country": country["name"],
                "Country ID": cid,
                "Currency": currency.get("name", ""),
                "Price / item": float(offer.get("value", 0)),
                "Stock": float(offer.get("amount", 0)),
                "Seller": offer.get("owner", {}).get("name", ""),
                "Seller country ID": offer.get("owner", {}).get("country_id"),
                "Import tax %": float(import_tax.get("rate", 0)),
                "Offer ID": offer.get("id"),
            })
        except Exception as e:
            results.append({
                "Country": country["name"],
                "Country ID": cid,
                "Currency": "",
                "Price / item": None,
                "Stock": None,
                "Seller": f"ERROR: {e}",
                "Seller country ID": None,
                "Import tax %": None,
                "Offer ID": None,
            })

        progress.progress(i / len(countries))
        time.sleep(0.03)

    status.empty()
    progress.empty()
    return pd.DataFrame(results)

@st.cache_data(ttl=300)
def get_gold_rate(currency_id):
    offers = api_get("/market/coin/get", {
        "currency_id": currency_id,
        "transaction": "SELL",
        "page": 1
    })



    if not offers:
        return None

    

    return float(offers[0]["rate"])
try:
    items = get_items()
    countries = get_countries()
except Exception as e:
    st.error(str(e))
    st.stop()

# Remove duplicate items, keeping the lowest ID for each name and quality
unique_items = {}

for item in items:
    if not item.get("name"):
        continue

    key = (
        item["name"].strip().lower(),
        int(item.get("quality", 0))
    )

    if key not in unique_items or int(item.get("id", 999999)) < int(unique_items[key].get("id", 999999)):
        unique_items[key] = item

choices = sorted(
    list(unique_items.values()),
    key=lambda x: (x["name"].lower(), -int(x.get("quality", 0)))
)

label_to_item = {
    f'{x["name"]} — Q{x.get("quality", "?")} (ID {x["id"]})': x
    for x in choices
}

default_index = 0
for idx, x in enumerate(choices):
    if x["name"].lower() == "ticket" and int(x.get("quality", 0)) == 5:
        default_index = idx
        break

selected_label = st.selectbox(
    "Item",
    list(label_to_item.keys()),
    index=default_index
)

selected = label_to_item[selected_label]
min_qty = st.number_input("Minimum stock required at the cheapest offer", min_value=1, value=1, step=1)

col1, col2 = st.columns(2)
with col1:
    do_gold = st.checkbox("Calculate approximate Gold equivalent", value=True)
with col2:
    include_unavailable = st.checkbox("Include unavailable countries", value=False)

if st.button("Scan all countries", type="primary"):
    try:
        df = scan_item(selected["id"], min_qty, include_unavailable)

        if df.empty:
            st.warning("No matching offers found.")
            st.write("Debug information:")
            st.write("Selected item:", selected)
            st.write("Item ID:", selected["id"])
            st.write("Minimum stock:", min_qty)
            st.write("Countries loaded:", len(countries))
            st.stop()

        st.success(f"Found {len(df)} matching offers!")

    except Exception as e:
        st.error(f"Scanner error: {type(e).__name__}: {e}")
        st.exception(e)
        st.stop()

    if do_gold:
        gold_rates = {}
        for currency_id, currency_name in [
            (c.get("currency", {}).get("id"), c.get("currency", {}).get("name"))
            for c in countries
        ]:
            if currency_id and currency_id != 1:
                try:
                    gold_rates[currency_id] = get_gold_rate(currency_id)
                except Exception:
                    gold_rates[currency_id] = None

        currency_id_by_name = {
            c.get("currency", {}).get("name"): c.get("currency", {}).get("id")
            for c in countries
        }
       
        def to_gold(row):
            cid = currency_id_by_name.get(row["Currency"])
            rate = gold_rates.get(cid) if cid else None
            if rate and rate > 0 and pd.notna(row["Price / item"]):
                return row["Price / item"] * rate
            return None

        df["Approx. Gold / item"] = df.apply(to_gold, axis=1)

        # Sort cheapest first by Gold price
        if do_gold and "Approx. Gold / item" in df.columns:
            df["Approx. Gold / item"] = pd.to_numeric(
                df["Approx. Gold / item"], errors="coerce"
            )
            df = df.sort_values(
                by="Approx. Gold / item",
                ascending=True,
                na_position="last"
            ).reset_index(drop=True)
        else:
            df = df.sort_values(
                by="Price / item",
                ascending=True,
                na_position="last"
            ).reset_index(drop=True)

        df.insert(0, "Rank", range(1, len(df) + 1))
            # Price per energy — food only
    if "Food" in selected["name"]:
        energy_by_quality = {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}
        energy = energy_by_quality.get(int(selected.get("quality", 0)))

        if energy and "Approx. Gold / item" in df.columns:
            gold_prices = pd.to_numeric(
                df["Approx. Gold / item"], errors="coerce"
            )
            df["Price / Energy"] = (gold_prices / energy).round(4)
        st.subheader(f'{selected["name"]} Q{selected.get("quality")} — cheapest by country')
        st.dataframe(df, use_container_width=True, hide_index=True)
                    

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        csv,
        file_name=f'eclesiar_{selected["name"].lower().replace(" ", "_")}_q{selected.get("quality")}.csv',
        mime="text/csv"
    )

    st.caption("Prices are live API market offers at scan time. Gold conversion is an estimate based on the currency market's best returned rate.")
st.subheader("Market Sales Activity")
with st.expander("Supabase Connection Test"):
    if st.button("Test Supabase Connection"):
        try:
            supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
            supabase_key = st.secrets["SUPABASE_KEY"]

            response = requests.get(
                f"{supabase_url}/rest/v1/market_sales_history",
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}"
                },
                params={"select": "id", "limit": "1"},
                timeout=15
            )

            if response.status_code == 200:
                st.success("Connected to Supabase successfully!")
            else:
                st.error(
                    f"Connection failed ({response.status_code}): "
                    f"{response.text[:300]}"
                )

        except Exception as e:
            st.error(f"Connection test failed: {e}")

import pandas as pd
from datetime import datetime, timedelta

try:
    countries = get_countries()

    country_names = {
        country["name"]: country["id"]
        for country in countries
        if country.get("name") and country.get("id") is not None
    }

    selected_country = st.selectbox(
        "Country",
        list(country_names.keys()),
        key="sales_country"
    )

    period = st.selectbox(
        "Sales period",
        ["Last 24 hours", "Last 7 days"],
        key="sales_period"
    )

    hours = 24 if period == "Last 24 hours" else 168
    cutoff = datetime.now() - timedelta(hours=hours)
    country_id = country_names[selected_country]

    if st.button("Calculate sales", key="calculate_sales"):
        sales = {}
        transactions_count = {}
        page = 1
        max_pages = 500
        records_checked = 0
        reached_cutoff = False

        progress = st.progress(0)
        status = st.empty()

        while page <= max_pages and not reached_cutoff:
            response = api_get(
                "/country/currency-transactions",
                {
                    "country_id": country_id,
                    "page": page
                }
            )

            if isinstance(response, dict):
                records = response.get("data", [])
                pagination = response.get("pagination", {})
                total_pages = int(pagination.get("total_pages", 1))
            else:
                records = response
                total_pages = 1

            if not records:
                break

            for record in records:
                timestamp = record.get("created_at")

                if not timestamp:
                    continue

                try:
                    transaction_time = datetime.fromisoformat(timestamp)
                except ValueError:
                    continue

                if transaction_time < cutoff:
                    reached_cutoff = True
                    break

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
            status.write(
                f"Checking page {page} of {total_pages:,} "
                f"({records_checked:,} records examined)"
            )

            progress.progress(
                min(page / max(total_pages, 1), 1.0)
            )

            if reached_cutoff or page >= total_pages:
                break

            page += 1

        progress.empty()
        status.empty()

        if reached_cutoff:
            st.success("Data coverage: Complete — reached the selected time cutoff.")
        elif page >= total_pages:
            st.warning("Data coverage: Reached the end of available transaction history.")
        else:
            st.warning(
                f"Data coverage: INCOMPLETE — stopped at the safety limit "
                f"of {max_pages} pages. Results may be lower than actual sales."
            )

        if sales:
            item_lookup = {
                int(item["id"]): item
                for item in get_items()
                if item.get("id") is not None
            }

            rows = []

            for item_id, quantity in sales.items():
                item = item_lookup.get(int(item_id), {})

                rows.append({
    "item_id": int(item_id),
    "item_name": item.get("name", f"Unknown item ({item_id})"),
    "quality": item.get("quality"),
    "units_purchased": quantity,
    "purchase_transactions": transactions_count[item_id],
    "Item": item.get("name", f"Unknown item ({item_id})"),
    "Quality": item.get("quality", "Unknown"),
    "Units purchased": quantity,
    "Purchase transactions": transactions_count[item_id],
    "Average units / transaction": round(
        quantity / transactions_count[item_id], 2
    )
})

            df_sales = pd.DataFrame(rows)
            df_sales = df_sales.sort_values(
                "Units purchased",
                ascending=False
            ).reset_index(drop=True)

            df_sales.insert(0, "Rank", range(1, len(df_sales) + 1))

            st.success(
                f"Found {len(df_sales)} items with recorded purchases. "
                f"Examined {records_checked:,} transaction records."
            )

            st.dataframe(df_sales, use_container_width=True, hide_index=True)

        else:
            st.info(
                "No matching purchases were found in the records checked."
            )

except Exception as e:
    st.error(f"Sales tracker failed: {e}")
