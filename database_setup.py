import sqlite3, sys
import pandas as pd
import config

REQUIRED = ["year", "line", "policies", "claims", "written_premium", "claims_paid"]
PLAUSIBLE = {"frequency": (0.0001, 0.5), "severity": (100, 100_000), "loss_ratio": (0.05, 2.0)}

def validate_claims(df):
    problems = []
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return [f"ERROR: missing columns {missing}"]
    num = REQUIRED[2:]

    # plain numbers only: "195.365.931" (thousands dots) makes the column text
    for col in ["year"] + num:
        bad = df[pd.to_numeric(df[col], errors="coerce").isna() & df[col].notna()]
        if not bad.empty:
            problems.append(f"ERROR: '{col}' not a plain number in:\n{bad}")
    if problems:
        return problems
    empty = df[REQUIRED].isna()
    # Kasko uses registered cars, so its policies may be empty
    empty.loc[df["line"].map(config.EXPOSURE_SOURCE).ne("policies"), "policies"] = False
    if empty.any().any():
        problems.append("ERROR: empty cells")
    if (df[num] <= 0).any().any():
        problems.append("ERROR: zero or negative values")
    if df.duplicated(["year", "line"]).any():
        problems.append("ERROR: duplicate (year, line) rows")
    if set(df["line"]) - set(config.LINES):
        problems.append("ERROR: unknown line codes")

    # gaps INSIDE a line's own range (a line may start later)
    for line, g in df.groupby("line"):
        yrs = set(g["year"])
        gaps = sorted(set(range(min(yrs), max(yrs) + 1)) - yrs)
        if gaps:
            problems.append(f"WARNING: {line} missing years {gaps}")

    r = pd.DataFrame({"year": df["year"], "line": df["line"],
                      "frequency": df["claims"] / df["policies"],
                      "severity": df["claims_paid"] / df["claims"],
                      "loss_ratio": df["claims_paid"] / df["written_premium"]})
    for col, (lo, hi) in PLAUSIBLE.items():
        bad = r[(r[col] < lo) | (r[col] > hi)]
        if not bad.empty:
            problems.append(f"WARNING: {col} outside [{lo}, {hi}]:\n{bad}")

    r = r.sort_values(["line", "year"])
    r["change"] = r.groupby("line")["severity"].pct_change()
    jumps = r[r["change"].abs() > 0.40]
    if not jumps.empty:
        problems.append(f"WARNING: severity moved >40% in one year:\n{jumps}")
    return problems
def build_cpi_table(monthly):
    m = monthly.copy()
    m["year"] = pd.to_datetime(m["date"]).dt.year
    a = m.groupby("year")["hicp"].agg(["mean", "count"]).reset_index()
    a = a[a["count"] == 12]
    return pd.DataFrame({"year": a["year"], "cpi_index": a["mean"] / a["mean"].iloc[-1]})

def build_database():
    claims = pd.read_csv(config.CLAIMS_CSV)
    problems = validate_claims(claims)
    for p in problems:
        print(p, "\n")
    if any(p.startswith("ERROR") for p in problems):
        sys.exit("Data has errors - database not built.")

    cpi = build_cpi_table(pd.read_csv(config.CPI_CSV))
    no_cpi = sorted(set(claims["year"]) - set(cpi["year"]))
    if no_cpi:
        print(f"WARNING: no CPI for {no_cpi}; left out of the severity trend")

    cars = pd.read_csv(config.REGISTERED_CARS_CSV)[["year", "cars"]]
    kasko_years = set(claims.loc[claims["line"] == "KASKO", "year"])
    if kasko_years - set(cars["year"]):
        sys.exit("ERROR: registered-car count missing for some Kasko years")

    with sqlite3.connect(config.DB_PATH) as conn:
        claims.to_sql("szz_claims", conn, if_exists="replace", index=False)
        cpi.to_sql("cpi", conn, if_exists="replace", index=False)
        cars.to_sql("registered_cars", conn, if_exists="replace", index=False)
    print(f"Built {config.DB_PATH}: {len(claims)} rows")

if __name__ == "__main__":
    build_database()


    