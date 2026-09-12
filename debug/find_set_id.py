"""
Find PokemonPriceTracker's actual id/slug for the Destined Rivals set by
paging through /api/v2/sets and filtering by name, instead of eyeballing
truncated raw JSON.
"""
import requests

API_KEY = "pokeprice_free_20a3678ba95e9215b15bc03bb64989ee389ce004c330fb33"
BASE = "https://www.pokemonpricetracker.com/api/v2/sets"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

limit = 100
offset = 0
seen = 0
found = []

while offset < 1000:  # safety cap -- ~10 pages, way more than should be needed
    resp = requests.get(
        BASE,
        headers=HEADERS,
        params={"sortBy": "releaseDate", "sortOrder": "desc", "limit": limit, "offset": offset},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    batch = payload.get("data", [])
    if not batch:
        print(f"No more sets after offset={offset}. Stopping.")
        break

    seen += len(batch)
    for s in batch:
        if "destined" in (s.get("name") or "").lower():
            found.append(s)

    print(f"  checked {seen} sets so far (offset={offset})...")
    if found:
        break
    if not payload.get("metadata", {}).get("hasMore", False):
        break
    offset += limit

print()
if found:
    print("Found it:")
    for s in found:
        print(f"  name={s.get('name')!r}")
        print(f"  id={s.get('id')!r}")
        print(f"  tcgPlayerId={s.get('tcgPlayerId')!r}")
        print(f"  cardCount={s.get('cardCount')!r}  releaseDate={s.get('releaseDate')!r}")
else:
    print(f"Scanned {seen} sets total -- nothing matched 'destined' in the name.")
    print("The name in their data might differ from what we expect -- worth checking manually.")
