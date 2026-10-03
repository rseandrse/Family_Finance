#!/usr/bin/env python3
"""Turn every bank statement into one standard table: work/transactions.csv

Usage: python3 normalize.py work/sources.json [--out work/transactions.csv]

sources.json is a list, one entry per statement file:
{
  "file": "uploads/wise.csv",            # path to the statement
  "account": "Wise",                     # how the account is called on the dashboard
  "sheet": 0,                            # Excel sheet (name or index), optional
  "header_row": 0,                       # row index of the column names in the raw grid
  "encoding": "utf-8-sig", "delimiter": ",",   # CSV only, optional (auto if absent)
  "date": "Date",                        # date column
  "date_format": "%d-%m-%Y",             # strptime format, optional (pandas guesses, dayfirst)
  "amount": "Amount",                    # signed amount column  …or…
  "debit": "Debit", "credit": "Credit",  # two columns: money out / money in (positive numbers)
  "invert": false,                       # true if the bank shows spending as positive
  "decimal": ".",                        # "," for 1.234,56 style numbers
  "description": ["Description", "Merchant", "Payment Reference"],  # joined with " | "
  "balance": "Running Balance",          # balance after the operation, optional
  "currency": "Currency",                # optional: column with the operation currency (code)
  "account_currency": "USD",             # optional: the whole file is in this currency
  "keep_currency": "EUR",                # optional: keep only rows in this currency (drop the rest)
  "skip_regex": "Previous balance|Opening balance|Closing balance",  # rows to drop (matched on description)
  "time": "Date Time", "time_format": "%d-%m-%Y %H:%M:%S.%f"       # optional, better ordering
}
Output columns: date, amount, currency, account, description, balance, seq
Amounts stay in their original currency here; build.py converts them to the family's main currency
(family.json "currency") with the rates from work/fx.json (see fx_rates.py).
(seq = chronological order inside the account, so balances can be read correctly).
"""
import sys, json, io, re, argparse
import pandas as pd


def detect_encoding(raw):
    """utf-8 first; otherwise pick the single-byte code page that yields the most letters (Cyrillic or Latin)."""
    try:
        raw.decode("utf-8-sig"); return "utf-8-sig"
    except UnicodeDecodeError:
        pass
    import re as _re
    best, enc = -1, "latin-1"
    for e in ("cp1251", "cp1252", "koi8-r", "cp866", "latin-1"):
        try:
            t = raw[:200000].decode(e)
        except UnicodeDecodeError:
            continue
        score = len(_re.findall(r"[а-яА-ЯёЁ]", t)) * (2 if e == "cp1251" else 1) - len(_re.findall(r"[ÃÂÐÑ][\x80-\xbf]|[ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ]{3,}", t)) * 3
        if score > best:
            best, enc = score, e
    return enc


def sstr(x):
    """Series -> plain str Series, NaN -> "" (pandas 3 keeps NaN in astype(str))."""
    return x.map(lambda v: "" if v is None or (isinstance(v, float) and v != v) else str(v))


def to_num(s, decimal="."):
    s = sstr(s).str.replace(" ", "", regex=False).str.replace(" ", "", regex=False)
    s = s.str.replace(r"[€$£A-Za-z]", "", regex=True)
    if decimal == ",":
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    else:
        s = s.str.replace(",", "", regex=False)
    return pd.to_numeric(s.replace({"": None, "nan": None, "None": None}), errors="coerce")


def read(src):
    f = src["file"]
    h = src.get("header_row", 0)
    if f.lower().endswith((".xls", ".xlsx", ".xlsm")):
        return pd.read_excel(f, header=h, sheet_name=src.get("sheet", 0))
    raw = open(f, "rb").read()
    enc = src.get("encoding") or detect_encoding(raw)
    txt = raw.decode(enc)
    delim = src.get("delimiter") or max([",", ";", "\t", "|"], key="\n".join(txt.splitlines()[:20]).count)
    return pd.read_csv(io.StringIO(txt), sep=delim, header=h, dtype=str, engine="python")


def norm_one(src):
    df = read(src)
    df.columns = [str(c).strip() for c in df.columns]
    dec = src.get("decimal", ".")
    num = lambda col: pd.to_numeric(col, errors="coerce") if pd.api.types.is_numeric_dtype(col) else to_num(col, dec)
    if "amount" in src:
        amt = num(df[src["amount"]])
    else:
        d = num(df[src["debit"]])
        c = num(df[src["credit"]])
        amt = c.fillna(0) - d.fillna(0).abs()
    if src.get("invert"):
        amt = -amt
    cols = src.get("description") or []
    if isinstance(cols, str):
        cols = [cols]
    desc = df[cols].apply(sstr).agg(lambda r: " | ".join([v.strip() for v in r if v and v.strip()]), axis=1) if cols else ""
    dcol = df[src["date"]]
    if pd.api.types.is_datetime64_any_dtype(dcol):
        date = dcol
    elif src.get("date_format"):
        date = pd.to_datetime(sstr(dcol).str.strip(), format=src["date_format"], errors="coerce")
    else:
        ds = sstr(dcol).str.strip()
        if ds.str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.8:
            date = pd.to_datetime(ds.str[:10], format="%Y-%m-%d", errors="coerce")  # ISO: never day-first
        else:
            date = pd.to_datetime(ds, errors="coerce", dayfirst=True)
    out = pd.DataFrame({"date": date, "amount": amt, "account": src["account"], "description": desc})
    if src.get("balance"):
        b = df[src["balance"]]
        out["balance"] = num(b)
    else:
        out["balance"] = None
    if src.get("time"):
        out["_t"] = pd.to_datetime(sstr(df[src["time"]]), format=src.get("time_format"), errors="coerce")
    if src.get("currency"):
        out["currency"] = sstr(df[src["currency"]]).str.strip().str.upper()
    else:
        out["currency"] = (src.get("account_currency") or "").upper()
    if src.get("keep_currency"):
        out = out[out["currency"].isin(["", src["keep_currency"].upper()])]
    if src.get("skip_regex"):
        out = out[~out.description.str.contains(src["skip_regex"], case=False, regex=True, na=False)]
    out["_row"] = range(len(out))
    out = out[out.date.notna() & out.amount.notna()]
    # chronological order: newest-first files are reversed so that balances read correctly
    asc = out.date.is_monotonic_increasing or (out.date.iloc[0] <= out.date.iloc[-1] if len(out) else True)
    if "_t" in out and out["_t"].notna().all():
        out = out.sort_values(["_t", "_row"])
    elif not asc:
        out = out.iloc[::-1]
    else:
        out = out.sort_values(["date", "_row"], kind="stable")
    return out.drop(columns=[c for c in ("_t", "_row") if c in out])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources")
    ap.add_argument("--out", default="work/transactions.csv")
    a = ap.parse_args()
    srcs = json.load(open(a.sources))
    frames = []
    for s in srcs:
        x = norm_one(s)
        print(f"{s['account']:<28} {s['file']:<60} {len(x):>5} rows  {x.date.min().date() if len(x) else ''} … {x.date.max().date() if len(x) else ''}  sum {x.amount.sum():,.2f}")
        frames.append(x)
    df = pd.concat(frames, ignore_index=True)
    df["seq"] = df.groupby("account").cumcount()
    df["date"] = df.date.dt.strftime("%Y-%m-%d")
    df.to_csv(a.out, index=False)
    print(f"\n→ {a.out}: {len(df)} operations, accounts: {sorted(df.account.unique())}")
    cm = df.assign(c=df.currency.replace("", "?")).groupby("c").size().sort_values(ascending=False)
    print("   currencies by operations: " + ", ".join(f"{c} {n}" for c, n in cm.items()) + ("  ('?' = not stated in the statement: set account_currency)" if "?" in cm.index else ""))
    # balance sanity check
    for acc, g in df.groupby("account"):
        if g.balance.notna().sum() < 2:
            continue
        g = g[g.balance.notna()]
        pred = g.balance.shift(1) + g.amount
        bad = ((pred - g.balance).abs() > 0.02).iloc[1:].sum()
        print(f"   balance check {acc}: {'OK' if bad == 0 else str(bad) + ' rows do not chain — check sort order / sign'}")


if __name__ == "__main__":
    main()
