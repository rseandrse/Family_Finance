#!/usr/bin/env python3
"""Study the family's data before choosing settings: who owns which account, income sources,
transfers between own accounts (also between partners), and signals of kids, pets, car, rent, travel.

Usage: python3 profile_data.py [--work work]
Read the output, then confirm the conclusions with the family and write family.json / rules.json.
"""
import argparse, re
import pandas as pd

SIGNALS = {
    "дети (школа, сад, кружки, игрушки)": r"SCHOOL|COLLEGE|COLEGIO|ESCOLA|ESCUELA|KINDERGARTEN|GUARDERIA|NURSERY|KITA|TOYS|JUGUET|JOGUET|LEGO|CAMP\b|CAMPAMENTO|ШКОЛА|ДЕТСК|САДИК|ИГРУШК",
    "питомцы": r"VET|VETERIN|ZOOPLUS|TIENDANIMAL|KIWOKO|MASCOT|PETS?\b|ANIMAL|ЗООМАГ|ВЕТКЛИН",
    "машина (топливо, парковки, страховка)": r"SHELL|REPSOL|CEPSA|\bBP\b|ESSO|GALP|IONITY|TESLA|PARKING|APARCA|GASOLIN|FUEL|PEAJE|TOLL|АЗС|ЛУКОЙЛ",
    "аренда": r"RENT\b|ALQUILER|LLOGUER|MIETE|LOYER|АРЕНДА",
    "ипотека / кредиты": r"MORTGAGE|HIPOTECA|PRESTAMO|PRÉSTEC|LOAN|LEASING|FINANC|КРЕДИТ|ИПОТЕК",
    "поездки (билеты, отели)": r"AIRLINE|AIRWAYS|VUELING|RYANAIR|EASYJET|IBERIA|BOOKING|AIRBNB|HOTEL|EXPEDIA|RENFE|SNCF|TRAINLINE",
    "подписки": r"NETFLIX|SPOTIFY|APPLE\.COM/BILL|GOOGLE|YOUTUBE|DISNEY|HBO|ICLOUD|ADOBE|MICROSOFT|OPENAI|ANTHROPIC",
    "наличные": r"\bATM\b|CASH|RETIRADA|REINTEGRO|БАНКОМАТ|НАЛИЧН",
    "переводы людям (Bizum, СБП и т. п.)": r"BIZUM|SENT MONEY TO|TRANSFER TO|ПЕРЕВОД|СБП|REVOLUT|PAYPAL \*?[A-Z]+ [A-Z]+$",
}


def key(s):
    s = str(s).upper().split(" | ")[0]
    s = re.sub(r"\d{3,}", "", s)
    return re.sub(r"\s+", " ", s).strip()[:40]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--work", default="work"); a = ap.parse_args()
    df = pd.read_csv(f"{a.work}/transactions.csv", dtype={"description": str})
    df["d"] = pd.to_datetime(df.date); df["k"] = df.description.map(key); df["month"] = df.date.str[:7]
    nm = df.month.nunique()
    print(f"Операций: {len(df)} · месяцев: {nm} ({df.date.min()} … {df.date.max()}) · счетов: {df.account.nunique()}\n")

    if "currency" in df:
        df["currency"] = df.currency.fillna("").str.upper()
        cm = df.assign(c=df.currency.replace("", "?")).groupby("c").agg(n=("amount", "size"), accs=("account", "nunique"))
        cm = cm.sort_values("n", ascending=False)
        print("== Валюты ==")
        for c, r in cm.iterrows():
            print(f"- {c}: {int(r.n)} оп. ({r.n/len(df):.0%}), счетов: {int(r.accs)}")
        main = cm.index[0]
        print(f"  → основная валюта: {main} — в ней ведётся большинство операций, в ней и показываем дашборд."
              + (" Остальные пересчитает build.py по курсу месяца (fx_rates.py)." if len(cm) > 1 else ""))
        if "?" in cm.index:
            print("  ! у части файлов валюта не указана — задайте account_currency в sources.json")
        print()
    print("== Счета ==")
    for acc, g in df.groupby("account"):
        print(f"- {acc}: {len(g)} оп., {g.date.min()} … {g.date.max()}, пришло {g[g.amount>0].amount.sum():,.0f}, ушло {-g[g.amount<0].amount.sum():,.0f}, остаток в выписке: {'да' if g.balance.notna().any() else 'нет'}")
        names = g.description.str.extract(r"(?i)(?:card ?holder|titular|cardholder)[: ]+([A-ZА-Я][\w]+ [A-ZА-Я][\w]+)")[0].dropna()
        if len(names):
            print(f"    владелец по выписке: {names.value_counts().index[0]}")

    print("\n== Регулярные поступления (кандидаты в источники дохода) ==")
    inc = df[df.amount > 0]
    rec = inc.groupby("k").agg(n=("amount", "size"), months=("month", "nunique"), total=("amount", "sum"), avg=("amount", "mean"), acc=("account", "first")).sort_values("total", ascending=False)
    for k, r in rec[(rec.months >= max(2, nm // 3)) & (rec.avg >= 200)].head(12).iterrows():
        print(f"- {k}: {r.months} мес., в среднем {r.avg:,.0f}, всего {r.total:,.0f} ({r.acc})")
    big1 = rec[(rec.months < max(2, nm // 3)) & (rec.total >= 1000)].head(8)
    if len(big1):
        print("  разовые крупные поступления (спросить, что это):")
        for k, r in big1.iterrows():
            print(f"  · {k}: {r.total:,.0f} ({r.acc})")

    print("\n== Переводы между своими счетами (одинаковая сумма, разные счета, ±3 дня) ==")
    out = df[df.amount < 0].reset_index(); inn = df[df.amount > 0].reset_index()
    pairs = out.merge(inn, left_on=out.amount.abs().round(2), right_on=inn.amount.round(2), suffixes=("_o", "_i"))
    pairs = pairs[(pairs.account_o != pairs.account_i) & ((pairs.d_i - pairs.d_o).dt.days.abs() <= 3)]
    if len(pairs):
        pat = pairs.groupby(["account_o", "k_o", "account_i", "k_i"]).agg(n=("amount_i", "size"), total=("amount_i", "sum")).sort_values("total", ascending=False)
        for (ao, ko, ai, ki), r in pat.head(15).iterrows():
            print(f"- {ao} «{ko}» → {ai} «{ki}»: {int(r.n)} раз, {r.total:,.0f}")
        print("  → такие пары почти всегда внутренние переводы (в том числе между партнёрами): правило type=internal для обеих сторон.")
    else:
        print("- пар не найдено (если счета партнёров ведутся отдельно, проверьте переводы между ними вручную)")

    print("\n== Признаки состава семьи и образа жизни ==")
    U = df.description.fillna("").str.upper()
    for name, rx in SIGNALS.items():
        m = U.str.contains(rx, regex=True) & (df.amount < 0)
        if m.any():
            top = df[m].groupby("k").amount.sum().sort_values().head(4)
            print(f"- {name}: {m.sum()} оп., {-df[m].amount.sum():,.0f} · " + "; ".join(f"{k} {-v:,.0f}" for k, v in top.items()))
        else:
            print(f"- {name}: не найдено")

    print("\n== Крупнейшие получатели (первые кандидаты в правила) ==")
    sp = df[df.amount < 0].groupby("k").agg(total=("amount", "sum"), n=("amount", "size"), months=("month", "nunique")).sort_values("total").head(25)
    for k, r in sp.iterrows():
        print(f"- {k}: {-r.total:,.0f} · {int(r.n)} оп. · {int(r.months)} мес.")

    print("""
Что решить с семьёй по этим данным:
1. Чьи это счета (accountOwners в family.json) и сколько взрослых показывать (adults: 1 или 2).
2. Есть ли дети (noKids). Если детей нет, но есть питомец, можно переименовать категорию kids:
   "kidsName": "Питомец", "categoryNames": {"kids": "Питомец: корм и ветеринар"}.
3. Источники дохода (incomeGroups) и правила для них (who = чей доход).
4. Внутренние переводы — правила type=internal, иначе траты и доходы задвоятся.
5. Что считать «не в бюджете» (работа, проекты, компенсации).""")


if __name__ == "__main__":
    main()
