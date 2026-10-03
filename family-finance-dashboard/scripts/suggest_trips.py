#!/usr/bin/env python3
"""Suggest candidate trips: clusters of days with flights / hotels / travel bookings.

Usage: python3 suggest_trips.py [--work work] [--gap 3]
Prints windows with dates, amount and the merchants seen, to confirm with the family
and turn into work/trips.json (see references/files.md).
"""
import argparse, json, os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import classify, load_json, pretty, HERE

ap = argparse.ArgumentParser(); ap.add_argument("--work", default="work"); ap.add_argument("--gap", type=int, default=3)
a = ap.parse_args()
fam = load_json(f"{a.work}/family.json", {})
rules = load_json(f"{a.work}/rules.json", []) + load_json(os.path.join(HERE, "..", "assets", "rules.starter.json"), [])
df = pd.read_csv(f"{a.work}/transactions.csv", dtype={"description": str})
df = df[df.date.str.startswith(str(fam.get("year", "")))].copy()
df = classify(df, rules)
t = df[(df["type"] == "exp") & (df.cat == "travel")].copy()
t["d"] = pd.to_datetime(t.date)
t = t.sort_values("d")
win, out = [], []
for _, r in t.iterrows():
    if win and (r.d - win[-1].d).days > a.gap:
        out.append(win); win = []
    win.append(r)
if win:
    out.append(win)
for w in out:
    s, e = w[0].d, w[-1].d
    near = df[(pd.to_datetime(df.date) >= s - pd.Timedelta(days=1)) & (pd.to_datetime(df.date) <= e + pd.Timedelta(days=2)) & (df["type"] == "exp")]
    print(f"\n{s.date()} … {e.date()}  travel bookings {(-sum(x.amount for x in w)):,.0f} · all spending in window {(-near.amount.sum()):,.0f}")
    for x in w[:8]:
        print(f"   {x.date}  {-x.amount:>9.2f}  {x.account:<16} {pretty(x.description)}")
    other = near.assign(p=near.description.map(pretty)).groupby("p").amount.sum().sort_values().head(8)
    print("   other spending nearby: " + "; ".join(f"{k} {-v:.0f}" for k, v in other.items()))
print("\nA booking can be made weeks before the trip: ask the family where they went and when, then write work/trips.json.")
