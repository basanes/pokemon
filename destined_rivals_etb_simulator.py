"""
Destined Rivals (SV10) Elite Trainer Box -- Monte Carlo EV Simulator
======================================================================
Answers: "If I pay EUR X for this ETB, what's the probability I come
out ahead if I open it and sell every card at current market price?"

DATA SOURCES (snapshot -- prices move constantly, refresh before
trusting this for a real purchase decision):

  - Pull rates: TCGplayer's 8,000+ pack opening study for Destined
    Rivals (reported via deltiasgaming.com, independently cross-checked
    against tcgtalk.com's EV writeup -- both report identical tier odds:
    Double Rare 1/5, Ultra Rare 1/16, Illustration Rare 1/12,
    Special Illustration Rare 1/94, Hyper Rare 1/149)
  - Card prices: PriceCharting market data via tcgtalk.com, snapshotted
    September 2026
  - Box structure (9 packs + 1 promo per ETB): retailer product listings

ASSUMPTIONS (all editable below -- this is a model, not a guarantee):
  - No selling fees or shipping are deducted, per your request -- this
    is *gross* resale value. On eBay/TCGplayer you'd realistically keep
    roughly 85-90% of these numbers after fees.
  - Cards within a rarity tier are pulled with equal probability (actual
    per-card print ratios within a tier aren't published anywhere)
  - "Standard Rare" and the bulk/reverse-holo portion of each pack use
    pool averages only, since no source breaks those down card-by-card
    -- their contribution to variance is tiny next to the SIR tier
  - The ETB promo card value is a rough placeholder -- check its actual
    going rate and edit PROMO_CARD_VALUE_USD if you want to be precise

Validation: this model's implied EV/pack ($5.31) independently reproduces
tcgtalk.com's own published EV/pack ($5.30) to within rounding -- good
sign the pull-rate model and price data are being combined correctly.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 1. DATA
# ---------------------------------------------------------------------------

# Rare-slot pull rates: TCGplayer 8,000+ pack study (deltiasgaming.com / tcgtalk.com)
RARE_SLOT_RATES = {
    "hyper_rare": 1 / 149,
    "special_illustration_rare": 1 / 94,
    "illustration_rare": 1 / 12,
    "ultra_rare": 1 / 16,
    "double_rare": 1 / 5,
}
RARE_SLOT_RATES["standard_rare"] = 1 - sum(RARE_SLOT_RATES.values())

# Card-level prices (USD) by tier. Source: PriceCharting via tcgtalk.com, Sept 2026.
CARD_PRICES_USD = {
    "hyper_rare": [7.77, 7.61],
    "special_illustration_rare": [
        484.07, 201.33, 151.12, 92.54, 90.90, 60.43, 59.99, 35.07,
        28.99, 28.07, 23.60, 22.55, 20.19, 19.67, 13.68,
    ],
    "illustration_rare": [
        61.75, 30.00, 26.41, 24.03, 18.86, 14.85, 11.38, 10.78, 10.47,
        9.99, 9.41, 8.95, 7.55, 6.13, 5.95, 5.54, 5.45, 5.24, 5.19,
        5.01, 4.75, 4.31, 4.10, 4.01, 3.90, 3.90, 3.89, 3.35, 3.26,
        2.95, 2.50, 1.87, 1.77, 1.65, 1.56, 1.50, 1.25,
    ],
    "ultra_rare": [9.00, 6.68, 4.58, 3.60, 3.45, 3.34, 2.46, 2.26],
    "double_rare": [
        1.61, 1.40, 1.30, 1.28, 1.19, 1.17, 1.17, 1.09, 1.00,
        0.99, 0.99, 0.96, 0.75, 0.75, 0.73, 0.73, 0.68,
    ],
    "standard_rare": [1.06],  # pool average only -- no public per-card split
}

GUARANTEED_VALUE_PER_PACK_USD = 0.80 + 1.60  # bulk commons/uncommons + reverse holo, pool avg
PACKS_PER_ETB = 9
PROMO_CARD_VALUE_USD = 1.75  # Team Rocket's Wobbuffet ETB promo -- rough placeholder, check & edit

EUR_USD_RATE = 1.164  # update this before you run it for real


# ---------------------------------------------------------------------------
# 2. LIVE PRICE REFRESH
#    Needs internet the sandbox this was built in doesn't have (egress is
#    locked to package registries), so it's untested from my end -- but it's
#    written against PokemonPriceTracker's documented v2 API and will run
#    fine on your own machine. Field names (`rarity`, `prices.market`) are
#    my best read of their docs -- print resp.json() once to confirm the
#    actual shape before trusting it blindly.
# ---------------------------------------------------------------------------

POKEMONPRICETRACKER_API_KEY = "pokeprice_free_20a3678ba95e9215b15bc03bb64989ee389ce004c330fb33"


def fetch_live_prices(set_id="destined-rivals"):
    """Pull current card prices from PokemonPriceTracker and reshape them
    into the same {tier: [prices]} structure as CARD_PRICES_USD."""
    import requests

    url = "https://www.pokemonpricetracker.com/api/v2/cards"
    headers = {"Authorization": f"Bearer {POKEMONPRICETRACKER_API_KEY}"}
    params = {"set": set_id, "fetchAllInSet": "true"}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    cards = resp.json()["data"]

    by_tier = {}
    for card in cards:
        tier = (card.get("rarity") or "").strip().lower().replace(" ", "_")
        price = (card.get("prices") or {}).get("market")
        if price:
            by_tier.setdefault(tier, []).append(float(price))
    return by_tier


# ---------------------------------------------------------------------------
# 3. MONTE CARLO ENGINE (vectorised -- 200k boxes runs in well under a second)
# ---------------------------------------------------------------------------

def simulate_boxes(n, rng, card_prices=CARD_PRICES_USD):
    tiers = list(RARE_SLOT_RATES.keys())
    probs = np.array([RARE_SLOT_RATES[t] for t in tiers])

    tier_idx = rng.choice(len(tiers), size=(n, PACKS_PER_ETB), p=probs)
    pack_hit_values = np.empty((n, PACKS_PER_ETB))

    for i, tier in enumerate(tiers):
        mask = tier_idx == i
        count = int(mask.sum())
        if count:
            pack_hit_values[mask] = rng.choice(card_prices[tier], size=count)

    floor = PACKS_PER_ETB * GUARANTEED_VALUE_PER_PACK_USD + PROMO_CARD_VALUE_USD
    return pack_hit_values.sum(axis=1) + floor


def run(cost, currency="EUR", n=200_000, seed=42, card_prices=CARD_PRICES_USD):
    rng = np.random.default_rng(seed)
    totals_usd = simulate_boxes(n, rng, card_prices)

    cost_usd = cost * EUR_USD_RATE if currency == "EUR" else cost
    profit_usd = totals_usd - cost_usd

    to_display = (lambda x: x / EUR_USD_RATE) if currency == "EUR" else (lambda x: x)

    return {
        "n": n,
        "currency": currency,
        "cost": cost,
        "expected_value": to_display(totals_usd.mean()),
        "expected_profit": to_display(profit_usd.mean()),
        "prob_profit": float((profit_usd > 0).mean()),
        "median_profit": to_display(np.median(profit_usd)),
        "p5_profit": to_display(np.percentile(profit_usd, 5)),
        "p95_profit": to_display(np.percentile(profit_usd, 95)),
        "max_profit": to_display(profit_usd.max()),
        "break_even_cost": to_display(totals_usd.mean()),
        "profit_distribution": to_display(profit_usd),  # for plotting/export
    }


# ---------------------------------------------------------------------------
# 4. REPORT
# ---------------------------------------------------------------------------

def print_report(r):
    c = "EUR " if r["currency"] == "EUR" else "$"
    print(f"\nDestined Rivals ETB -- Monte Carlo simulation ({r['n']:,} boxes)")
    print(f"  Cost you're evaluating:   {c}{r['cost']:.2f}")
    print(f"  Expected resale value:    {c}{r['expected_value']:.2f}")
    print(f"  Expected profit/loss:     {c}{r['expected_profit']:+.2f}")
    print(f"  Probability of profit:    {r['prob_profit']*100:.1f}%")
    print(f"  Median outcome:           {c}{r['median_profit']:+.2f}")
    print(f"  Bad luck (5th pct):       {c}{r['p5_profit']:+.2f}")
    print(f"  Good luck (95th pct):     {c}{r['p95_profit']:+.2f}")
    print(f"  Best simulated outcome:   {c}{r['max_profit']:+.2f}")
    print(f"  Break-even price:         {c}{r['break_even_cost']:.2f}  (pay under this to be +EV)")
    print(f"  (Fees/shipping NOT deducted -- this is gross resale value.)\n")


def save_histogram(r, path=None):
    """
    Save a profit/loss histogram from the simulation and (best-effort) pop
    it open automatically. Needs matplotlib.

    HOW TO READ THIS CHART
    ------------------------------------------------------------------
    * Each bar = how many of the N simulated box-openings landed in that
      profit/loss bracket. Taller bar = more common outcome -- NOT worth
      more.
    * X-axis = profit/loss in your chosen currency. Left of the dashed
      black line (0) is a loss; right of it is a profit.
    * The orange line is the MEDIAN outcome -- the "typical" box. It's
      usually a bigger loss than you'd guess from the average alone,
      because a handful of huge Special Illustration Rare pulls drag the
      mean toward break-even without being typical themselves -- most
      boxes don't hit one.
    * The x-axis is deliberately clipped to the 1st-99th percentile, NOT
      the full range. Without this, a single lucky ~$480 pull anywhere in
      200,000 simulated boxes stretches the axis so far right that the
      bar you actually care about -- the everyday result clustered near
      zero -- shrinks to an invisible sliver. The caption printed on the
      chart (and below) says exactly what fraction got clipped and how
      high the best case went, so nothing is hidden, just zoomed past.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    c = "EUR" if r["currency"] == "EUR" else "USD"
    data = r["profit_distribution"]

    if path is None:
        # One file per cost tested, e.g. profit_distribution_EUR55.png,
        # instead of overwriting the same profit_distribution.png each run.
        path = SCRIPT_DIR / f"profit_distribution_{r['currency']}{r['cost']:g}.png"
    else:
        path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)  # never silently fail on a missing folder

    lo, hi = np.percentile(data, [1, 99])
    clipped_frac = float(((data < lo) | (data > hi)).mean())
    sym = "EUR " if r["currency"] == "EUR" else "$"
    caption = (
        f"Zoomed to the 1st-99th percentile -- {clipped_frac * 100:.1f}% of runs "
        f"(mostly SIR/Hyper Rare pulls) land outside this view, up to a best "
        f"case of {sym}{r['max_profit']:+,.0f}."
    )

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.hist(data, bins=60, range=(lo, hi), color="#4C72B0", edgecolor="white", linewidth=0.3)
    ax.axvline(0, color="black", linewidth=1, linestyle="--", label="break-even")
    ax.axvline(np.median(data), color="orange", linewidth=1.5, label="median outcome")
    ax.set_title(f"Destined Rivals ETB -- simulated profit/loss (n={r['n']:,})")
    ax.set_xlabel(f"Profit / Loss ({c})")
    ax.set_ylabel("Number of simulated boxes")
    ax.legend()
    fig.text(0.5, 0.01, caption, ha="center", fontsize=8, color="dimgray", wrap=True)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, dpi=150)
    print(f"Saved histogram to {path}")
    print(f"  ({caption})")
    _try_open(path)


def _try_open(path):
    """Best-effort: pop the image open in the OS's default viewer. Never
    fatal if it doesn't work -- the path was already printed above."""
    try:
        # Pylance/Pyright statically assumes a single OS (whatever it thinks
        # you're on) and greys out the other two branches as "unreachable" --
        # that's just its platform narrowing, not a real bug. All three
        # branches are real code that runs fine; only one executes per OS.
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["xdg-open", str(path)], check=False,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def prompt_for_inputs():
    """Asks for cost/currency/plot interactively. Used whenever the script is
    launched without a --cost flag -- e.g. double-clicked on Windows, run via
    an IDE's Run button, or just `python destined_rivals_etb_simulator.py`
    with no arguments. Without this, those launch methods silently fall back
    to the placeholder EUR 55 used for the walkthrough."""
    print("Destined Rivals ETB simulator -- interactive mode")
    print("(next time, `--cost 65 --currency USD` etc. skips these prompts)\n")

    while True:
        raw = input("How much did you pay (or would pay) for the ETB? ").strip().lstrip("€$")
        try:
            cost = float(raw)
            break
        except ValueError:
            print("  Enter a plain number, e.g. 55 or 55.50")

    currency = ""
    while currency not in ("EUR", "USD"):
        currency = input("Currency -- EUR or USD? [EUR]: ").strip().upper() or "EUR"
        if currency not in ("EUR", "USD"):
            print("  Please type EUR or USD.")

    want_plot = input("Save a profit/loss chart? [Y/n]: ").strip().lower() != "n"

    return cost, currency, want_plot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Destined Rivals ETB EV simulator")
    parser.add_argument("--cost", type=float, default=None, help="what you paid (or would pay); omit to be asked interactively")
    parser.add_argument("--currency", choices=["EUR", "USD"], default="EUR")
    parser.add_argument("--n", type=int, default=200_000, help="number of simulated boxes")
    parser.add_argument("--live", action="store_true", help="fetch fresh prices from PokemonPriceTracker first")
    parser.add_argument("--no-plot", action="store_true", help="skip saving the profit/loss chart")
    args = parser.parse_args()

    if args.cost is None:
        # No --cost given -- most likely launched without any flags at all.
        # Ask instead of silently reusing the walkthrough's placeholder.
        cost, currency, want_plot = prompt_for_inputs()
    else:
        cost, currency, want_plot = args.cost, args.currency, not args.no_plot

    prices = CARD_PRICES_USD
    if args.live:
        print("Fetching live prices from PokemonPriceTracker...")
        fetched = fetch_live_prices()
        prices = {**CARD_PRICES_USD, **{k: v for k, v in fetched.items() if v}}

    result = run(cost, currency=currency, n=args.n, card_prices=prices)
    print_report(result)

    if want_plot:
        save_histogram(result)
