#!/usr/bin/env python3
"""Build every dashboard document from work/transactions.csv and the family's rule files.

Usage:  python3 build.py [--work work] [--out out]

Reads (in --work):
  transactions.csv   output of normalize.py                          (required)
  family.json        family settings, see references/files.md        (required)
  rules.json         family-specific classification rules            (optional, checked first)
  trips.json         trips with dates                                (optional)
  manual.json        purchases paid outside the statements           (optional)
  notes.json         {"YYYY-MM": ["observation", ...]}               (optional)
  review.json        questions for the family                        (optional)
Always appends the starter rules from ../assets/rules.starter.json after the family rules.

Writes (in --out):
  months/YYYY-MM.json, tx/YYYY-MM.json, accounts-YYYY.json, config-main.json,
  review/<id>.json, report.md, upload_plan.json
"""
import os, re, json, argparse, glob
from collections import defaultdict
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CATS = ["housing", "kids", "groceries", "travel", "hobby_s", "hobby_m", "transport", "cafe", "fun", "shopping", "health", "other"]
OFF = "Оплата вне выписок"
SYM = {"EUR": "€", "USD": "$", "GBP": "£", "RUB": "₽", "GEL": "₾", "UAH": "₴", "KZT": "₸", "TRY": "₺", "PLN": "zł", "CZK": "Kč",
       "AMD": "֏", "BYN": "Br", "ILS": "₪", "INR": "₹", "JPY": "¥", "CNY": "¥", "AED": "AED", "CHF": "CHF", "RSD": "RSD", "THB": "฿", "UZS": "UZS"}


def nice(v):
    """Round a threshold to a 'nice' number: 1, 2, 2.5, 5 × 10^n."""
    import math
    if v <= 0:
        return 0
    p = 10 ** math.floor(math.log10(v)); f = v / p
    return int((1 if f < 1.5 else 2 if f < 2.25 else 2.5 if f < 3.5 else 5 if f < 7.5 else 10) * p)


def load_json(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def pretty(s):
    s = str(s or "")
    s = s.split(" | ")[0] if len(s.split(" | ")[0].strip()) > 2 else s
    s = re.sub(r"^(card transaction of [\d.,]+ \w+ issued by |paypal \*|sq \*|sumup \*|sp |mgp\*|www\.|visa |mastercard |pos |compra |pago en |card payment to |sent money to |paid to |received money from )", "", s, flags=re.I)
    s = re.sub(r"\s+\d{5,}.*$", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -*|/")
    if not re.search(r"[а-яА-Я]", s) and s.isupper():
        s = s.title()
    return s[:48] or "Без названия"


def classify(df, rules):
    df["type"] = None; df["cat"] = None; df["label"] = None; df["group"] = None; df["reason"] = None; df["rule"] = None; df["who"] = None
    U = df.description.fillna("").str.upper()
    for i, r in enumerate(rules):
        m = df["type"].isna()
        if r.get("match"):
            m &= U.str.contains(r["match"], case=False, regex=True, na=False)
        if r.get("account"):
            m &= df.account.str.contains(r["account"], regex=True, case=False, na=False)
        if r.get("dir") == "out":
            m &= df.amount < 0
        if r.get("dir") == "in":
            m &= df.amount > 0
        if "min" in r:
            m &= df.amount.abs() >= r["min"]
        if "max" in r:
            m &= df.amount.abs() <= r["max"]
        if r.get("from"):
            m &= df.date >= r["from"]
        if r.get("to"):
            m &= df.date <= r["to"]
        if not m.any():
            continue
        t = r.get("type") or ("inc" if r.get("dir") == "in" else "exp")
        df.loc[m, "type"] = t
        df.loc[m, "cat"] = r.get("cat") if t == "exp" else None
        df.loc[m, "label"] = r["label"] if r.get("label") else df.loc[m, "description"].map(pretty)
        df.loc[m, "group"] = r.get("group")
        df.loc[m, "reason"] = r.get("reason")
        df.loc[m, "who"] = r.get("who")
        df.loc[m, "rule"] = r.get("id", f"rule{i}")
    un = df["type"].isna()
    df["unclassified"] = un
    out = un & (df.amount < 0)
    inn = un & (df.amount >= 0)
    df.loc[out, "type"] = "exp"; df.loc[out, "cat"] = "other"; df.loc[out, "label"] = df.loc[out, "description"].map(pretty)
    df.loc[inn, "type"] = "inc"; df.loc[inn, "label"] = "Поступление: " + df.loc[inn, "description"].map(pretty)
    bad = df["type"].eq("exp") & ~df["cat"].isin(CATS)
    if bad.any():
        raise SystemExit(f"Unknown category in rules: {sorted(df.loc[bad,'cat'].astype(str).unique())}. Allowed: {CATS}")
    return df


TK = [("Билеты", r"AIR|AIRL|VUELING|RYANAIR|EASYJET|IBERIA|LUFTHANSA|KLM|NORWEGIAN|WIZZ|AEROFLOT|TURKISH|EMIRATES|QATAR|KIWI\.COM|OMIO|RENFE|SNCF|TRAINLINE|FLIXBUS|DB BAHN|OUIGO|TRENITALIA|FLIGHT|AIRWAYS"),
      ("Жильё", r"HOTEL|BOOKING|BKG\*|AIRBNB|HOSTEL|RESORT|APART|MARRIOTT|HILTON|IBIS|NOVOTEL|ACCOR|EXPEDIA|GUESTHOUSE|VILLA"),
      ("Транспорт", r"TAXI|UBER(?!.*EATS)|BOLT|LYFT|CABIFY|FREENOW|DIDI|PARKING|PARK|RENT ?A ?CAR|HERTZ|AVIS|SIXT|EUROPCAR|FUEL|SHELL|REPSOL|CEPSA|ESSO|TOTAL|IONITY|TOLL|PEAJE|AUTOPISTA|METRO|BUS")]
CAT2K = {"cafe": "Еда", "groceries": "Еда", "transport": "Транспорт"}


def trip_kind(desc, cat0):
    U = str(desc).upper()
    for k, rx in TK:
        if re.search(rx, U):
            return k
    return CAT2K.get(cat0, "Покупки и прочее")


def tag_trips(df, trips):
    df["trip"] = None; df["cat0"] = df["cat"]
    default_cats = {"travel", "cafe", "groceries", "transport", "fun", "shopping", "health", "other"}
    U = df.description.fillna("").str.upper()
    for t in trips:
        exp = df["type"].eq("exp") & df.trip.isna()
        m = exp & (df.date >= t["start"]) & (df.date <= t["end"])
        if t.get("match"):
            m &= U.str.contains(t["match"], case=False, regex=True, na=False)
        else:
            m &= df.cat.isin(t.get("cats", default_cats))
        if t.get("accounts"):
            m &= df.account.str.contains(t["accounts"], regex=True, na=False)
        if t.get("exclude"):
            m &= ~U.str.contains(t["exclude"], case=False, regex=True, na=False)
        for x in t.get("extra", []):
            m |= exp & (df.date >= x.get("from", "0000")) & (df.date <= x.get("to", "9999")) & U.str.contains(x["match"], case=False, regex=True, na=False)
        df.loc[m, "trip"] = t["id"]
        df.loc[m, "cat"] = t.get("cat", "travel")
        df.loc[m, "label"] = t["name"]
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="work")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    W, O = a.work, a.out
    fam = load_json(f"{W}/family.json", None)
    if fam is None:
        raise SystemExit(f"{W}/family.json is missing — see references/files.md")
    year = str(fam.get("year"))
    base = (fam.get("currency") or "EUR").upper()
    cur_sym = fam.get("currencySymbol") or SYM.get(base, base)
    rules = load_json(f"{W}/rules.json", []) + load_json(os.path.join(HERE, "..", "assets", "rules.starter.json"), [])
    trips = load_json(f"{W}/trips.json", [])
    manual = load_json(f"{W}/manual.json", [])
    notes = load_json(f"{W}/notes.json", {})
    review = load_json(f"{W}/review.json", [])
    big_thr = fam.get("bigThreshold")
    big_skip = fam.get("bigExcludeRegex", "")
    small_inc = fam.get("smallIncomeThreshold")
    groups = fam.get("incomeGroups", [])

    df = pd.read_csv(f"{W}/transactions.csv", dtype={"description": str, "account": str, "currency": str})
    # ---- currencies: everything is shown in the family's main currency (family.json "currency")
    if "currency" not in df:
        df["currency"] = ""
    df["currency"] = df.currency.fillna("").str.upper().replace("", base)
    fx = load_json(f"{W}/fx.json", {})
    other = df.currency != base
    if other.any():
        missing = []
        def rate(c, m):
            r = (fx.get(c) or {}).get(m)
            if r is None:
                missing.append(f"{c} {m}")
            return r or 0
        rates = [rate(c, d[:7]) if o else 1.0 for c, d, o in zip(df.currency, df.date, other)]
        if missing:
            raise SystemExit("Нет курса для: " + ", ".join(sorted(set(missing))) + " — запустите fx_rates.py или заполните work/fx.json")
        df["amount_orig"] = df.amount
        df["amount"] = (df.amount * pd.Series(rates, index=df.index)).round(2)
        df["balance"] = df.balance * pd.Series(rates, index=df.index)
        df.loc[other, "description"] = df.loc[other, "description"].fillna("") + df.loc[other].apply(lambda r: f" ({r.amount_orig:.2f} {r.currency})", axis=1)
        print("Пересчитано в " + base + ": " + ", ".join(f"{c} {n} оп." for c, n in df[other].currency.value_counts().items()))
    df = df[df.date.str.startswith(year)].copy()
    df["month"] = df.date.str[:7]
    df = classify(df, rules)
    df = tag_trips(df, trips)
    # ---- thresholds scale with the family's currency and budget when not set explicitly
    avg_exp = max(1.0, -df[df["type"] == "exp"].groupby("month").amount.sum().mean()) if (df["type"] == "exp").any() else 1.0
    if big_thr is None:
        big_thr = nice(avg_exp * 0.12)
    if small_inc is None:
        small_inc = nice(avg_exp * 0.04)
    item_min = nice(avg_exp * 0.005)
    df["detail"] = df.description.map(pretty)
    for d in ("months", "tx", "review"):
        os.makedirs(f"{O}/{d}", exist_ok=True)
    for f in glob.glob(f"{O}/months/*.json") + glob.glob(f"{O}/tx/*.json") + glob.glob(f"{O}/review/*.json"):
        os.remove(f)

    months = sorted(df.month.unique().tolist() + [m["month"] for m in manual if m["month"].startswith(year)])
    months = sorted(set(months))
    report = []
    docs, txdocs = {}, {}
    for m in months:
        g = df[df.month == m]
        doc = {"month": m}
        # income
        inc = []
        I = g[g["type"] == "inc"]
        for (lab, grp), gg in I.groupby(["label", I["group"].fillna("")]):
            v = round(gg.amount.sum(), 2)
            if abs(v) >= 0.5:
                inc.append({"source": lab, "who": (gg.who.dropna().iloc[0] if "who" in gg and gg.who.notna().any() else "Семья"), "amount": v, "group": grp or "Прочее"})
        keep = [x for x in inc if x["amount"] >= small_inc or x["group"] in groups]
        small = round(sum(x["amount"] for x in inc if x not in keep), 2)
        if small:
            keep.append({"source": "Мелкие поступления", "who": "Семья", "amount": small, "group": "Прочее"})
        doc["income"] = sorted(keep, key=lambda x: -x["amount"])
        # expenses
        E = g[g["type"] == "exp"]
        exps = []
        for c, gc in E.groupby("cat"):
            it = (-gc.groupby("label").amount.sum()).sort_values(ascending=False)
            exps.append({"cat": c, "amount": round(-gc.amount.sum(), 2), "items": [{"label": k, "amount": round(v, 2)} for k, v in it.head(5).items() if v >= item_min]})
        doc["expenses"] = exps
        # events
        ev = []
        for t in trips:
            x = df[df.trip == t["id"]]
            if len(x) and t["start"][:7] == m:
                tm = x.groupby("detail").amount.agg(["sum", "size"]).sort_values("sum")
                det = [f"{len(x)} операций с {x.date.min()[8:10]}.{x.date.min()[5:7]} по {x.date.max()[8:10]}.{x.date.max()[5:7]}"] + \
                      [f"{k2} — {-r2['sum']:.2f} {cur_sym}" + (f" ({int(r2['size'])} оп.)" if r2["size"] > 1 else "") for k2, r2 in tm.head(7).iterrows()]
                br = (-x.groupby(x.apply(lambda r: trip_kind(r.description, r.cat0), axis=1)).amount.sum()).sort_values(ascending=False)
                ev.append({"type": "trip", "cat": t.get("cat", "travel"), "title": t["name"], "short": t.get("short"), "amount": round(-x.amount.sum(), 2),
                           "dates": f"{t['start'][8:10]}.{t['start'][5:7]}–{t['end'][8:10]}.{t['end'][5:7]}", "details": det,
                           "br": {k3: int(round(v3)) for k3, v3 in br.items() if v3 > 0}})
        NB = E[E.trip.isna()]
        # regular payments (the same statement in most months: rent, tuition, loan) are not "big events"
        regular = set(lab for lab, nmon in df[(df["type"] == "exp") & df.trip.isna()].groupby("label").month.nunique().items() if nmon >= max(3, 0.6 * len(months)))
        for (lab, c), gb in NB.groupby(["label", "cat"]):
            tot = -gb.amount.sum()
            if tot < big_thr or c in ("groceries", "cafe") or lab in regular or (big_skip and re.search(big_skip, lab, re.I)):
                continue
            rr = gb.sort_values(["date", "seq"])
            det = [f"{q.date[8:10]}.{q.date[5:7]} · {-q.amount:.2f} {cur_sym} · {q.account} · {str(q.description)[:90]}" for _, q in rr.head(6).iterrows()]
            if len(rr) > 6:
                det.append(f"и ещё {len(rr)-6} операций")
            ev.append({"type": "big", "title": lab, "amount": round(tot, 2), "cat": c, "details": det})
        # excluded
        X = g[g["type"] == "excl"]
        doc["excluded"] = [{"title": lab + (" — возврат" if pos and (X[(X.label == lab)].amount < 0).any() else ""), "amount": round(abs(gx.amount.sum()), 2), "kind": "inc" if gx.amount.sum() > 0 else "exp",
                            "reason": (gx.reason.dropna().iloc[0] if gx.reason.notna().any() else "Не в бюджете"),
                            "details": [f"{q.date[8:10]}.{q.date[5:7]} · {q.amount:+.2f} {cur_sym} · {q.account} · {str(q.description)[:80]}" for _, q in gx.head(6).iterrows()]}
                           for (lab, pos), gx in X.groupby(["label", X.amount > 0])]
        doc["notes"] = notes.get(m, [])
        # tx rows
        rows = []
        for _, r in g.sort_values(["date", "account", "seq"]).iterrows():
            if r["type"] == "internal":
                continue
            amt = round(-r.amount, 2) if r["type"] in ("exp", "excl") else round(r.amount, 2)
            kind = r["cat"] if r["type"] == "exp" else ("excluded" if r["type"] == "excl" else "income")
            det = r.detail if r.detail != r.label and not str(r.label).endswith(r.detail) else ""
            rows.append([r.date[8:10], amt, kind, r.label, r.account, det])
        # manual purchases
        for x in [x for x in manual if x["month"] == m]:
            c = x.get("cat", "other")
            e = next((e for e in doc["expenses"] if e["cat"] == c), None)
            if e is None:
                e = {"cat": c, "amount": 0, "items": []}; doc["expenses"].append(e)
            e["amount"] = round(e["amount"] + x["amount"], 2)
            e["items"] = sorted([{"label": x["title"], "amount": x["amount"]}] + e["items"], key=lambda i: -i["amount"])[:5]
            ev.append({"type": "big", "title": x["title"], "amount": x["amount"], "cat": c, "details": [x.get("note", "Добавлено вручную: оплата прошла не через выписки")]})
            rows.insert(0, ["—", x["amount"], c, x["title"], OFF, ""])
            if x.get("financed"):
                t2 = x.get("incomeTitle", "Средства на покупку: " + x["title"])
                doc["income"].append({"source": t2, "who": "Семья", "amount": x["amount"], "group": "Прочее"})
                rows.insert(0, ["—", x["amount"], "income", t2, OFF, ""])
        ev.sort(key=lambda v: -v["amount"])
        doc["events"] = ev
        docs[m] = doc
        txdocs[m] = {"month": m, "rows": rows}

    # accounts
    accts = []
    for acc, ga in df.groupby("account"):
        ga = ga.sort_values("seq")
        hasbal = ga.balance.notna().sum() > 0
        acur = ga.currency.mode().iloc[0] if len(ga) else base
        prev = None
        if hasbal:
            fb = ga[ga.balance.notna()].iloc[0]
            prev = round(float(fb.balance) - float(fb.amount), 2)
        ms = {}
        for m in months:
            g = ga[ga.month == m]
            inc_ = g[g["type"] == "inc"].amount.sum(); exp_ = -g[g["type"] == "exp"].amount.sum()
            tin = g[(g["type"] == "internal") & (g.amount > 0)].amount.sum(); tout = -g[(g["type"] == "internal") & (g.amount < 0)].amount.sum()
            xl = g[g["type"] == "excl"].amount.sum()
            E = g[g["type"] == "exp"]
            cats = (-E.groupby("cat").amount.sum()).round(2)
            top = (-E.groupby("label").amount.sum()).sort_values(ascending=False).head(5).round(2)
            d = dict(inc=round(inc_, 2), exp=round(exp_, 2), tin=round(tin, 2), tout=round(tout, 2), xl=round(xl, 2),
                     cats={k: float(v) for k, v in cats.items() if abs(v) > 0.5}, top=[[k, float(v)] for k, v in top.items()], start=None, end=None)
            if hasbal:
                b = g[g.balance.notna()]
                end = round(float(b.balance.iloc[-1]), 2) if len(b) else prev
                d["start"], d["end"] = prev, end
                d["diff"] = round(end - prev - g.amount.sum(), 2) if acur == base else None
                prev = end
            ms[m] = d
        accts.append({"id": f"acc{len(accts)+1}", "name": acc, "months": ms, **({"currency": acur} if acur != base else {})})
    if manual:
        ms = {}
        for m in months:
            xs = [x for x in manual if x["month"] == m]
            cats = defaultdict(float)
            for x in xs:
                cats[x.get("cat", "other")] += x["amount"]
            ms[m] = dict(inc=sum(x["amount"] for x in xs if x.get("financed")), exp=sum(x["amount"] for x in xs), tin=0, tout=0, xl=0,
                         cats=dict(cats), top=[[x["title"], x["amount"]] for x in xs], start=None, end=None)
        accts.append({"id": "OFF", "name": OFF, "offStatement": True, "months": ms})
    for i, ac in enumerate(accts):
        own = (fam.get("accountOwners") or {}).get(ac["name"])
        if own:
            ac["owner"] = own
        col = (fam.get("accountColors") or {}).get(ac["name"])
        if col:
            ac["color"] = col

    # write
    for m in months:
        json.dump(docs[m], open(f"{O}/months/{m}.json", "w"), ensure_ascii=False)
        json.dump(txdocs[m], open(f"{O}/tx/{m}.json", "w"), ensure_ascii=False)
    json.dump({"year": year, "accounts": accts}, open(f"{O}/accounts-{year}.json", "w"), ensure_ascii=False)
    cfg = {k: fam[k] for k in ("title", "currency", "currencySymbol", "currencyLabel", "adults", "kidsDesc", "kidsName", "noKids", "incomeGroups", "excludedNote", "excludedTile", "categoryNames") if k in fam}
    cfg["currency"] = base; cfg.setdefault("currencySymbol", cur_sym); cfg["bigThreshold"] = big_thr
    json.dump(cfg, open(f"{O}/config-main.json", "w"), ensure_ascii=False)
    for q in review:
        q = dict(q); q.setdefault("status", "open")
        json.dump(q, open(f"{O}/review/{q['id']}.json", "w"), ensure_ascii=False)

    # upload plan (batches of ≤ 40 docs and ≤ 900 KB)
    items = [("config", "main", f"{O}/config-main.json"), ("accounts", year, f"{O}/accounts-{year}.json")]
    items += [("months", m, f"{O}/months/{m}.json") for m in months] + [("tx", m, f"{O}/tx/{m}.json") for m in months]
    items += [("review", q["id"], f"{O}/review/{q['id']}.json") for q in review]
    batches, curb, size = [], [], 0
    for c, d, p in items:
        s = os.path.getsize(p)
        if s > 950_000:
            print(f"WARNING: {p} is {s/1e6:.2f} MB — too big for one document; split that month's tx (see references/database.md)")
        if curb and (len(curb) >= 40 or size + s > 900_000):
            batches.append(curb); curb, size = [], 0
        curb.append({"op": "set", "collection": c, "doc_id": d, "file_path": os.path.abspath(p)}); size += s
    if curb:
        batches.append(curb)
    json.dump(batches, open(f"{O}/upload_plan.json", "w"), ensure_ascii=False, indent=1)

    # report
    R = report
    R.append(f"# Отчёт сборки {year}\n")
    tot_i = sum(sum(i["amount"] for i in docs[m]["income"]) for m in months)
    tot_o = sum(sum(e["amount"] for e in docs[m]["expenses"]) for m in months)
    R.append(f"Пришло {tot_i:,.0f} · ушло {tot_o:,.0f} · итог {tot_i-tot_o:,.0f} {cur_sym}\n")
    R.append(f"Основная валюта: {base}. Порог «Крупного»: {big_thr:,} {cur_sym} · мелкие поступления до {small_inc:,} · статьи от {item_min:,}")
    if other.any():
        R.append("Пересчитано из других валют: " + ", ".join(f"{c}: {n} оп. [{(fx.get(c) or {}).get('_source','')}]" for c, n in df[other].currency.value_counts().items()))
    R.append("## По месяцам\n| Месяц | Пришло | Ушло | Итог | Операций |\n|---|---|---|---|---|")
    for m in months:
        i_ = sum(i["amount"] for i in docs[m]["income"]); o_ = sum(e["amount"] for e in docs[m]["expenses"])
        R.append(f"| {m} | {i_:,.0f} | {o_:,.0f} | {i_-o_:,.0f} | {len(txdocs[m]['rows'])} |")
    ct = defaultdict(float)
    for m in months:
        for e in docs[m]["expenses"]:
            ct[e["cat"]] += e["amount"]
    R.append("\n## Категории за год\n" + "\n".join(f"- {c}: {v:,.0f}" for c, v in sorted(ct.items(), key=lambda x: -x[1])))
    un = df[df.unclassified & df.trip.isna()]
    R.append(f"\n## Не распознано правилами: {len(un)} операций на {un.amount.abs().sum():,.0f} {cur_sym}")
    R.append("Главные (по сумме) — для каждой добавьте правило в rules.json или задайте вопрос семье:")
    top_un = un.assign(p=un.description.map(pretty), a=un.amount.abs()).groupby(["p", un.amount > 0]).agg(sum=("a", "sum"), n=("a", "size"), acc=("account", "first"), ex=("description", "first")).sort_values("sum", ascending=False).head(60)
    for (p, isin), r in top_un.iterrows():
        R.append(f"- {'ПРИХОД ' if isin else ''}{p} — {r['sum']:,.2f} ({r.n} оп., {r.acc}) · пример: {str(r.ex)[:80]}")
    R.append(f"\n## Переводы между своими счетами (internal): {df[df['type']=='internal'].amount.abs().sum():,.0f} {cur_sym} в обе стороны")
    R.append("\n## Поездки\n" + "\n".join(f"- {t['name']}: {(-df[df.trip==t['id']].amount.sum()):,.0f} {cur_sym}, {int((df.trip==t['id']).sum())} оп." for t in trips))
    R.append("\n## Счета: сходимость остатков")
    for ac in accts:
        bad = [m for m, v in ac["months"].items() if v.get("diff") not in (None, 0, 0.0) and abs(v["diff"]) > 0.05]
        last = ac["months"][months[-1]]
        R.append(f"- {ac['name']}: конец {last.get('end')} · {'OK' if not bad else 'не сходится в ' + ', '.join(bad)}")
    R.append("\n## Размер документов tx (лимит ~1 МБ)\n" + ", ".join(f"{m}: {os.path.getsize(f'{O}/tx/{m}.json')//1024} КБ" for m in months))
    R.append(f"\n## Загрузка\n{len(batches)} пакет(ов) в {O}/upload_plan.json")
    open(f"{O}/report.md", "w").write("\n".join(R))
    print("\n".join(R[:20 + len(months)]))
    print(f"\n… полный отчёт: {O}/report.md")


if __name__ == "__main__":
    main()
