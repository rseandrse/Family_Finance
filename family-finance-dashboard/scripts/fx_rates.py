#!/usr/bin/env python3
"""Exchange rates for operations in other currencies -> work/fx.json

Usage: python3 fx_rates.py [--work work] [--base RUB]

The main currency is family.json "currency" (or --base). For every other currency found in
work/transactions.csv the script writes the monthly average rate "1 unit = X main currency":
  1) ECB rates via api.frankfurter.dev (monthly averages of daily rates) when both currencies are covered;
  2) otherwise the current rate from open.er-api.com, the same for every month (marked "approx").
If there is no internet, it writes a template with null rates: fill them in by hand (from the bank or a
central bank site) — build.py refuses to run while a used rate is missing.

fx.json format: {"USD": {"2026-01": 0.853, "2026-02": 0.861, "_source": "ECB monthly average"}}
"""
import argparse, json, os, urllib.request, statistics
import pandas as pd


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "family-finance"}), timeout=20) as r:
        return json.loads(r.read().decode())


def ecb_monthly(cur, base, months):
    start, end = months[0] + "-01", months[-1] + "-28"
    end = (pd.Timestamp(months[-1] + "-01") + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
    d = get(f"https://api.frankfurter.dev/v1/{start}..{end}?base={cur}&symbols={base}")
    by = {}
    for day, r in d.get("rates", {}).items():
        by.setdefault(day[:7], []).append(r[base])
    out = {m: round(statistics.mean(by[m]), 6) for m in months if m in by}
    last = None
    for m in months:  # fill gaps with the previous month
        if m in out:
            last = out[m]
        elif last is not None:
            out[m] = last
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--work", default="work"); ap.add_argument("--base")
    a = ap.parse_args()
    fam = json.load(open(f"{a.work}/family.json")) if os.path.exists(f"{a.work}/family.json") else {}
    base = (a.base or fam.get("currency") or "EUR").upper()
    df = pd.read_csv(f"{a.work}/transactions.csv", dtype={"currency": str})
    if "currency" not in df:
        print("transactions.csv has no currency column: everything is in one currency"); return
    df["currency"] = df.currency.fillna("").str.upper()
    others = sorted(c for c in df.currency.unique() if c and c != base)
    path = f"{a.work}/fx.json"
    fx = json.load(open(path)) if os.path.exists(path) else {}
    if not others:
        print(f"All operations are in {base} (or the currency is not stated) — no rates needed."); return
    try:
        ecb = set(get("https://api.frankfurter.dev/v1/currencies").keys())
    except Exception as e:
        ecb = set(); print("ECB rates unavailable:", e)
    for cur in others:
        months = sorted(df[df.currency == cur].date.str[:7].unique())
        n = int((df.currency == cur).sum())
        rates, src = {}, None
        if cur in ecb and base in ecb:
            try:
                rates = ecb_monthly(cur, base, months); src = "ECB monthly average (frankfurter.dev)"
            except Exception as e:
                print(f"{cur}: ECB failed ({e})")
        if len(rates) < len(months):
            try:
                d = get(f"https://open.er-api.com/v6/latest/{cur}")
                r = d["rates"][base]
                for m in months:
                    rates.setdefault(m, round(r, 6))
                src = (src + " + " if src else "") + f"approx: current rate {d.get('time_last_update_utc','')[:16]} (open.er-api.com)"
            except Exception as e:
                print(f"{cur}: no online rate ({e}) — fill fx.json by hand")
        fx[cur] = {**{m: rates.get(m, fx.get(cur, {}).get(m)) for m in months}, "_source": src or "manual"}
        print(f"{cur} → {base}: {n} operations · " + ", ".join(f"{m[5:]}: {v}" for m, v in fx[cur].items() if not m.startswith("_")) + f"  [{fx[cur]['_source']}]")
    json.dump(fx, open(path, "w"), ensure_ascii=False, indent=1)
    print(f"→ {path}")


if __name__ == "__main__":
    main()
