#!/usr/bin/env python3
"""Show the shape of a bank statement file so you can write its entry in sources.json.

Usage: python3 inspect_statement.py <file> [<file> ...]

Prints, for every file: format, detected encoding / delimiter (CSV), sheet names (Excel),
the first rows as the raw grid (so you can see where the header row is), the columns
under the guessed header, and columns that look like dates, amounts and balances.
"""
import sys, re, io
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_colwidth", 40)


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


def read_any(path, header=None, sheet=0):
    p = path.lower()
    if p.endswith((".xls", ".xlsx", ".xlsm")):
        return pd.read_excel(path, header=header, sheet_name=sheet)
    raw = open(path, "rb").read()
    enc = detect_encoding(raw)
    txt = raw.decode(enc)
    first = "\n".join(txt.splitlines()[:20])
    delim = max([",", ";", "\t", "|"], key=first.count)
    return pd.read_csv(io.StringIO(txt), sep=delim, header=header, dtype=str, engine="python"), enc, delim


def guess_header(grid):
    best, best_i = -1, 0
    for i in range(min(25, len(grid))):
        row = [str(v) for v in grid.iloc[i].tolist()]
        score = sum(1 for v in row if v and v not in ("nan", "NaT", "None") and not re.fullmatch(r"[-+\d.,:\s€$£/]+", v) and not re.match(r"^\d{4}-\d{2}-\d{2}", v))
        if score > best:
            best, best_i = score, i
    return best_i


def main():
    for path in sys.argv[1:]:
        print("=" * 100)
        print(path)
        p = path.lower()
        if p.endswith((".xls", ".xlsx", ".xlsm")):
            xl = pd.ExcelFile(path)
            print("format: excel · sheets:", xl.sheet_names)
            grid = pd.read_excel(path, header=None, sheet_name=0)
        else:
            grid, enc, delim = read_any(path)
            print(f"format: csv · encoding: {enc} · delimiter: {delim!r}")
        print(f"rows in grid: {len(grid)}")
        print("\n-- first 12 raw rows --")
        print(grid.head(12).to_string())
        h = guess_header(grid)
        print(f"\n-- guessed header row index: {h} --")
        cols = [str(c) for c in grid.iloc[h].tolist()]
        body = grid.iloc[h + 1:].reset_index(drop=True)
        body.columns = cols
        for c in cols:
            s = body[c].dropna().map(str).head(200)
            if not len(s):
                continue
            kind = []
            if s.str.match(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}").mean() > 0.7 or s.str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.7:
                kind.append("DATE?")
            if s.str.match(r"^-?[\d\s.,]+$").mean() > 0.8:
                kind.append("NUMBER?")
            print(f"  {c!r:40} {' '.join(kind):14} e.g. {s.iloc[0][:50]!r}")
        print("\n-- last 3 rows (to see the sort order and footer lines) --")
        print(body.tail(3).to_string())


if __name__ == "__main__":
    main()
