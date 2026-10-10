
# Eclesiar Price Scanner

A small Streamlit tool that scans Eclesiar's item market and compares the cheapest offer in every available country.

## What it does

- Loads all Eclesiar items automatically.
- Lets you select an item/quality (Q5 Ticket is selected automatically when available).
- Scans `/market/items/get` for every country.
- Finds the cheapest offer with at least the requested stock.
- Shows local price, stock, seller, seller country and import tax.
- Optionally estimates the price in Gold using Eclesiar's currency market.
- Exports the result as CSV.

## Requirements

Python 3.10+ is recommended.

Install:

    pip install -r requirements.txt

Run:

    streamlit run app.py

Then enter your Eclesiar API key in the app.

You can also set it as an environment variable:

    ECLESIAR_API_KEY="YOUR_KEY" streamlit run app.py

Do NOT put your API key into source code or share it publicly.

## API

The app uses Eclesiar's official API:
- `GET /server/items`
- `GET /countries`
- `GET /market/items/get`
- `GET /market/coin/get`

Eclesiar currently documents API-key authentication and a 50,000-request daily limit per API account.
