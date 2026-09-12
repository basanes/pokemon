"""
Minimal, standalone check of the PokemonPriceTracker API -- no simulator
logic involved at all. Just: does the call work, and what does it
actually return. Run this on its own:

    python check_api.py

Paste back everything it prints.
"""
import requests

API_KEY = "pokeprice_free_20a3678ba95e9215b15bc03bb64989ee389ce004c330fb33"
SET_ID = "destined-rivals"  # unverified guess -- this is exactly what we're checking


def show(label, resp):
    print(f"\n--- {label} ---")
    print("HTTP status:", resp.status_code)
    print(resp.text[:1500])


# Call 1: the exact query the simulator makes.
resp = requests.get(
    "https://www.pokemonpricetracker.com/api/v2/cards",
    headers={"Authorization": f"Bearer {API_KEY}"},
    params={"set": SET_ID, "fetchAllInSet": "true"},
    timeout=30,
)
show(f"GET /api/v2/cards?set={SET_ID}", resp)

# Call 2: list of sets, so if call 1 came back empty we can read off the
# real id/slug for Destined Rivals directly from this instead of guessing.
resp2 = requests.get(
    "https://www.pokemonpricetracker.com/api/v2/sets",
    headers={"Authorization": f"Bearer {API_KEY}"},
    params={"sortBy": "releaseDate", "sortOrder": "desc"},
    timeout=30,
)
show("GET /api/v2/sets", resp2)
