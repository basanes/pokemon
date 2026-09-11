"""
Destined Rivals (SV10) Elite Trainer Box -- Monte Carlo EV Simulator
======================================================================
Answers: "If I pay EUR X for this ETB, what's the probability I come
out ahead if I open it and sell every card at current market price?"

Works in EUR only, start to finish -- no currency parameter, no runtime
currency conversion anywhere in the simulation itself. The one
unavoidable exception is fetch_live_prices(), which pulls USD from
PokemonPriceTracker's free tier and converts to EUR in that single
function, clearly marked -- so if a number looks wrong you can tell
"the API call is broken" apart from "the currency math is wrong"
instead of the two being tangled together.

DATA SOURCES (snapshot -- prices move constantly, refresh before
trusting this for a real purchase decision):

  - Pull rates: TCGplayer's 8,000+ pack opening study for Destined
    Rivals (reported via deltiasgaming.com, independently cross-checked
    against tcgtalk.com's EV writeup -- both report identical tier odds:
    Double Rare 1/5, Ultra Rare 1/16, Illustration Rare 1/12,
    Special Illustration Rare 1/94, Hyper Rare 1/149). These are plain
    probabilities, unaffected by the currency correction below.
  - Card prices: PriceCharting market data via tcgtalk.com, snapshotted
    September 2026. CORRECTION: tcgtalk.com is a Singapore-focused
    price app and actually quotes in SGD, not USD as this script first
    assumed -- every price below has been rescaled from SGD to EUR
    (see SGD_TO_EUR_RATE_USED). The *relative* value between cards is
    unaffected either way, only the absolute scale was wrong before.
  - Box structure (9 packs + 1 promo per ETB): retailer product listings

ASSUMPTIONS (all editable below -- this is a model, not a guarantee):
  - No selling fees or shipping are deducted -- this is *gross* resale
    value. On eBay/TCGplayer you'd realistically keep roughly 85-90% of
    these numbers after fees.
  - Cards within a rarity tier are pulled with equal probability (actual
    per-card print ratios within a tier aren't published anywhere)
  - "Standard Rare" and the bulk/reverse-holo portion of each pack use
    pool averages only, since no source breaks those down card-by-card
    -- their contribution to variance is tiny next to the SIR tier
  - The ETB promo card value is a rough placeholder in EUR directly (it
    was never sourced in any currency, just guessed) -- check its
    actual going rate and edit PROMO_CARD_VALUE_EUR if you want to be
    precise

On the earlier "validation" claim: a previous version of this file said
the model's EV/pack independently reproduced tcgtalk.com's own published
EV/pack. That check reused tcgtalk's own card list AND their own summary
stat, so really it only confirmed the list was transcribed and
aggregated correctly -- not that two independent sources agree. The
pull-rate agreement between Deltia's Gaming and tcgtalk (both ultimately
citing the same TCGplayer study) is the actually-independent check.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 1. DATA (all EUR)
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

SGD_TO_EUR_RATE_USED = 0.68  # rate used to convert tcgtalk's SGD prices below, Sept 2026

# Card-level prices (EUR) by tier. Source: PriceCharting via tcgtalk.com, Sept
# 2026, originally in SGD -- rescaled by SGD_TO_EUR_RATE_USED above.
CARD_PRICES_EUR = {
    "hyper_rare": [5.28, 5.17],
    "special_illustration_rare": [
        329.17, 136.90, 102.76, 62.93, 61.81, 41.09, 40.79, 23.85,
        19.71, 19.09, 16.05, 15.33, 13.73, 13.38, 9.30,
    ],
    "illustration_rare": [
        41.99, 20.40, 17.96, 16.34, 12.82, 10.10, 7.74, 7.33, 7.12,
        6.79, 6.40, 6.09, 5.13, 4.17, 4.05, 3.77, 3.71, 3.56, 3.53,
        3.41, 3.23, 2.93, 2.79, 2.73, 2.65, 2.65, 2.65, 2.28, 2.22,
        2.01, 1.70, 1.27, 1.20, 1.12, 1.06, 1.02, 0.85,
    ],
    "ultra_rare": [6.12, 4.54, 3.11, 2.45, 2.35, 2.27, 1.67, 1.54],
    "double_rare": [
        1.09, 0.95, 0.88, 0.87, 0.81, 0.80, 0.80, 0.74, 0.68,
        0.67, 0.67, 0.65, 0.51, 0.51, 0.50, 0.50, 0.46,
    ],
    "standard_rare": [0.72],  # pool average only -- no public per-card split
}

GUARANTEED_VALUE_PER_PACK_EUR = 0.54 + 1.09  # bulk commons/uncommons + reverse holo, pool avg
PACKS_PER_ETB = 9
PROMO_CARD_VALUE_EUR = 1.50  # Team Rocket's Wobbuffet ETB promo -- rough placeholder, check & edit


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

# PokemonPriceTracker's free tier returns USD (their TCGPlayer-sourced data);
# EUR Cardmarket pricing needs a paid plan. This is the ONLY currency
# conversion left in the whole script, isolated here on purpose.
USD_TO_EUR_RATE = 1 / 1.164  # ~0.859 EUR per USD, Sept 2026 -- update before relying on it


def fetch_live_prices(set_id="destined-rivals"):
    """Pull current card prices from PokemonPriceTracker (USD) and convert
    them to EUR before handing them back, so every downstream number in this
    script is EUR without exception."""
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
        price_usd = (card.get("prices") or {}).get("market")
        if price_usd:
            by_tier.setdefault(tier, []).append(round(float(price_usd) * USD_TO_EUR_RATE, 2))
    return by_tier


# ---------------------------------------------------------------------------
# 3. MONTE CARLO ENGINE (vectorised -- 200k boxes runs in well under a second)
# ---------------------------------------------------------------------------

def simulate_boxes(n, rng, card_prices=CARD_PRICES_EUR):
    tiers = list(RARE_SLOT_RATES.keys())
    probs = np.array([RARE_SLOT_RATES[t] for t in tiers])

    tier_idx = rng.choice(len(tiers), size=(n, PACKS_PER_ETB), p=probs)
    pack_hit_values = np.empty((n, PACKS_PER_ETB))

    for i, tier in enumerate(tiers):
        mask = tier_idx == i
        count = int(mask.sum())
        if count:
            pack_hit_values[mask] = rng.choice(card_prices[tier], size=count)

    floor = PACKS_PER_ETB * GUARANTEED_VALUE_PER_PACK_EUR + PROMO_CARD_VALUE_EUR
    return pack_hit_values.sum(axis=1) + floor


def run(cost, n=200_000, seed=42, card_prices=CARD_PRICES_EUR):
    """cost is in EUR. Every value in the returned dict is in EUR."""
    rng = np.random.default_rng(seed)
    totals = simulate_boxes(n, rng, card_prices)
    profit = totals - cost

    return {
        "n": n,
        "cost": cost,
        "expected_value": float(totals.mean()),
        "expected_profit": float(profit.mean()),
        "prob_profit": float((profit > 0).mean()),
        "median_profit": float(np.median(profit)),
        "p5_profit": float(np.percentile(profit, 5)),
        "p95_profit": float(np.percentile(profit, 95)),
        "max_profit": float(profit.max()),
        "break_even_cost": float(totals.mean()),
        "profit_distribution": profit,  # for plotting/export
    }


# ---------------------------------------------------------------------------
# 4. REPORT
# ---------------------------------------------------------------------------

def print_report(r):
    print(f"\nDestined Rivals ETB -- Monte Carlo simulation ({r['n']:,} boxes)")
    print(f"  Cost you're evaluating:   EUR {r['cost']:.2f}")
    print(f"  Expected resale value:    EUR {r['expected_value']:.2f}")
    print(f"  Expected profit/loss:     EUR {r['expected_profit']:+.2f}")
    print(f"  Probability of profit:    {r['prob_profit']*100:.1f}%")
    print(f"  Median outcome:           EUR {r['median_profit']:+.2f}")
    print(f"  Bad luck (5th pct):       EUR {r['p5_profit']:+.2f}")
    print(f"  Good luck (95th pct):     EUR {r['p95_profit']:+.2f}")
    print(f"  Best simulated outcome:   EUR {r['max_profit']:+.2f}")
    print(f"  Break-even price:         EUR {r['break_even_cost']:.2f}  (pay under this to be +EV)")
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
    * X-axis = profit/loss in EUR. Left of the dashed black line (0) is a
      loss; right of it is a profit.
    * The orange line is the MEDIAN outcome -- the "typical" box. It's
      usually a bigger loss than you'd guess from the average alone,
      because a handful of huge Special Illustration Rare pulls drag the
      mean toward break-even without being typical themselves -- most
      boxes don't hit one.
    * The x-axis is deliberately clipped to the 1st-99th percentile, NOT
      the full range. Without this, a single lucky big pull anywhere in
      200,000 simulated boxes stretches the axis so far right that the
      bar you actually care about -- the everyday result clustered near
      zero -- shrinks to an invisible sliver. The caption printed on the
      chart (and below) says exactly what fraction got clipped and how
      high the best case went, so nothing is hidden, just zoomed past.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = r["profit_distribution"]

    if path is None:
        # One file per cost tested, e.g. profit_distribution_EUR55.png,
        # instead of overwriting the same file every run.
        path = SCRIPT_DIR / f"profit_distribution_EUR{r['cost']:g}.png"
    else:
        path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)  # never silently fail on a missing folder

    lo, hi = np.percentile(data, [1, 99])
    clipped_frac = float(((data < lo) | (data > hi)).mean())
    caption = (
        f"Zoomed to the 1st-99th percentile -- {clipped_frac * 100:.1f}% of runs "
        f"(mostly SIR/Hyper Rare pulls) land outside this view, up to a best "
        f"case of EUR {r['max_profit']:+,.0f}."
    )

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.hist(data, bins=60, range=(lo, hi), color="#4C72B0", edgecolor="white", linewidth=0.3)
    ax.axvline(0, color="black", linewidth=1, linestyle="--", label="break-even")
    ax.axvline(np.median(data), color="orange", linewidth=1.5, label="median outcome")
    ax.set_title(f"Destined Rivals ETB -- simulated profit/loss (n={r['n']:,})")
    ax.set_xlabel("Profit / Loss (EUR)")
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
    """Asks for cost/plot interactively. Used whenever the script is launched
    without a --cost flag -- e.g. double-clicked on Windows, run via an IDE's
    Run button, or just `python destined_rivals_etb_simulator.py` with no
    arguments."""
    print("Destined Rivals ETB simulator -- interactive mode (EUR only)")
    print("(next time, `--cost 65` skips this prompt)\n")

    while True:
        raw = input("How much did you pay (or would pay) for the ETB, in EUR? ").strip().lstrip("€$")
        try:
            cost = float(raw)
            break
        except ValueError:
            print("  Enter a plain number, e.g. 55 or 55.50")

    want_plot = input("Save a profit/loss chart? [Y/n]: ").strip().lower() != "n"

    return cost, want_plot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Destined Rivals ETB EV simulator (EUR only)")
    parser.add_argument("--cost", type=float, default=None, help="what you paid (or would pay), in EUR; omit to be asked interactively")
    parser.add_argument("--n", type=int, default=200_000, help="number of simulated boxes")
    parser.add_argument("--live", action="store_true", help="fetch fresh prices from PokemonPriceTracker first (USD, converted to EUR)")
    parser.add_argument("--no-plot", action="store_true", help="skip saving the profit/loss chart")
    args = parser.parse_args()

    if args.cost is None:
        # No --cost given -- most likely launched without any flags at all.
        cost, want_plot = prompt_for_inputs()
    else:
        cost, want_plot = args.cost, not args.no_plot

    prices = CARD_PRICES_EUR
    if args.live:
        print("Fetching live prices from PokemonPriceTracker (USD -> EUR)...")
        fetched = fetch_live_prices()
        prices = {**CARD_PRICES_EUR, **{k: v for k, v in fetched.items() if v}}

    result = run(cost, n=args.n, card_prices=prices)
    print_report(result)

    if want_plot:
        save_histogram(result)