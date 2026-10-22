# --- Files ---
DB_PATH = "szz_market.db"
CLAIMS_CSV = "data/szz_claims_raw.csv"
CPI_CSV = "data/hicp_slovenia_monthly.csv"
REGISTERED_CARS_CSV = "data/registered_cars.csv"
LINES = ["AO", "AO_PLUS", "KASKO"]
DATA_END_YEAR = 2023               # later years include foreign business
LINE_NAMES = {"AO": "MTPL (Motor Third-Party Liability)",
              "AO_PLUS": "AO+ (Driver Personal Accident)",
              "KASKO": "Comprehensive Motor (Kasko)"}

# --- Projection ---
PROJECTION_YEAR = 2026
CPI_INFLATION_PROJECTION = 0.025   # general inflation 2025 -> 2026

# --- Trend fitting ---
TREND_START_YEAR = None            # None = all years; Step 7 decides
SEVERITY_START_YEAR = {"AO": 2011, "AO_PLUS": 2011, "KASKO": 2011}
FREQUENCY_START_YEAR = {"AO": 2011, "AO_PLUS": 2011, "KASKO": 2011}
SEVERITY_BREAKS = {"AO": [], "AO_PLUS": [], "KASKO": []}
FREQUENCY_BREAKS = {"AO": [], "AO_PLUS": [], "KASKO": []}
FREQUENCY_EXCLUDED_YEARS = [2020, 2021]   # COVID: abnormal driving
EXPOSURE_SOURCE = {"AO": "policies", "AO_PLUS": "policies",
                   "KASKO": "registered_cars"}   # what frequency is per
EXPOSURE_METHOD = "trend"          # or "last"
EXPOSURE_TREND_YEARS = 5

# --- Simulation ---
N_SIMULATIONS = 10_000
RANDOM_SEED = 42
VAR_LEVEL = 0.995
FREQ_SEV_CORRELATION = None        # None = estimate from data
INCLUDE_PARAMETER_UNCERTAINTY = True