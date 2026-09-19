import sqlite3
import pandas as pd

def build_database():
    df_raw = pd.read_csv("data/szz_claims_raw.csv")
    with sqlite3.connect("szz_market.db") as conn:
        df_raw.to_sql("szz_claims", conn, if_exists="replace", index=False)

if __name__ == "__main__":
    build_database()

