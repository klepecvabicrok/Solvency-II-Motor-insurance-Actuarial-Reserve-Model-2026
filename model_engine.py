import sqlite3
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy import stats
import config

def get_kpi_data(db_path=config.DB_PATH):
    query = """
        SELECT c.year, c.line, c.policies, c.claims, c.written_premium,
               c.claims_paid, p.cpi_index, r.cars
        FROM szz_claims c LEFT JOIN cpi p ON p.year = c.year
        LEFT JOIN registered_cars r ON r.year = c.year
        ORDER BY c.line, c.year"""
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)
    if config.DATA_END_YEAR is not None:            # drop foreign-business years
        df = df[df["year"] <= config.DATA_END_YEAR].reset_index(drop=True)
    use_cars = df["line"].map(config.EXPOSURE_SOURCE).eq("registered_cars")
    df["exposure"] = np.where(use_cars, df["cars"], df["policies"])
    df["severity"] = df["claims_paid"] / df["claims"]
    df["frequency"] = df["claims"] / df["exposure"]
    df["loss_ratio"] = df["claims_paid"] / df["written_premium"]
    df["real_severity"] = df["severity"] / df["cpi_index"]   # 2025 euros
    return df

@dataclass
class TrendFit:
    coef: np.ndarray      # [intercept, slope, break dummies...]
    xtx_inv: np.ndarray   # (X'X)^-1, needed for parameter uncertainty
    sigma: float          # volatility: std dev of residuals
    dof: int              # degrees of freedom = n - parameters
    last_year: int
    breaks: list
    years: np.ndarray
    log_y: np.ndarray

    def design(self, years):
        years = np.atleast_1d(np.asarray(years))
        cols = [np.ones(len(years)), years - self.last_year]
        cols += [(years >= b).astype(float) for b in self.breaks]
        return np.column_stack(cols)

    def fitted(self, years):
        return self.design(years) @ self.coef

    @property
    def residuals(self):
        return self.log_y - self.fitted(self.years)

    @property
    def annual_growth(self):
        return float(np.exp(self.coef[1]) - 1)

    @property
    def coef_se(self):
        return np.sqrt(np.diag(self.sigma**2 * self.xtx_inv))

def fit_log_trend(years, values, breaks=()):
    years = np.asarray(years)
    log_y = np.log(np.asarray(values, dtype=float))
    breaks = [b for b in breaks if years.min() < b <= years.max()]

    tmp = TrendFit(np.zeros(2 + len(breaks)), None, 0.0, 0,
                   int(years.max()), breaks, years, log_y)
    X = tmp.design(years)
    n, p = X.shape
    if n - p < 2:
        raise ValueError(f"Only {n} points for {p} parameters")

    xtx_inv = np.linalg.inv(X.T @ X)
    coef = xtx_inv @ X.T @ log_y
    resid = log_y - X @ coef
    dof = n - p
    sigma = float(np.sqrt(resid @ resid / dof))
    return TrendFit(coef, xtx_inv, sigma, dof, int(years.max()), breaks, years, log_y)

def _fit_window(df):
    if config.TREND_START_YEAR is not None:
        df = df[df["year"] >= config.TREND_START_YEAR]
    return df

def fit_severity(df_line, line):
    d = _fit_window(df_line.dropna(subset=["real_severity"]))
    start = config.SEVERITY_START_YEAR.get(line)
    if start is not None:
        d = d[d["year"] >= start]
    return fit_log_trend(d["year"], d["real_severity"], config.SEVERITY_BREAKS.get(line, []))

def fit_frequency(df_line, line):
    d = _fit_window(df_line.dropna(subset=["frequency"]))
    start = config.FREQUENCY_START_YEAR.get(line)
    if start is not None:
        d = d[d["year"] >= start]
    d = d[~d["year"].isin(config.FREQUENCY_EXCLUDED_YEARS)]
    return fit_log_trend(d["year"], d["frequency"], config.FREQUENCY_BREAKS.get(line, []))

def project_exposure(df_line, target_year):
    d = df_line.sort_values("year")
    if config.EXPOSURE_METHOD == "last":
        return float(d.iloc[-1]["exposure"])
    recent = d.tail(config.EXPOSURE_TREND_YEARS)
    fit = fit_log_trend(recent["year"], recent["exposure"])
    return float(np.exp(fit.fitted([target_year])[0]))

def cpi_base_year(db_path=config.DB_PATH):
    # the year where cpi_index = 1.0, read from the cpi table itself:
    # DATA_END_YEAR cuts the claims at 2023, but real euros are still 2025 euros
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT MAX(year) FROM cpi").fetchone()[0])

def cpi_projection_factor(df, target_year):
    return (1 + config.CPI_INFLATION_PROJECTION) ** (target_year - cpi_base_year())

def residual_correlation(fit_a, fit_b):
    a = dict(zip(fit_a.years, fit_a.residuals))
    b = dict(zip(fit_b.years, fit_b.residuals))
    common = sorted(set(a) & set(b))
    if len(common) < 3:
        return 0.0
    return float(np.corrcoef([a[y] for y in common], [b[y] for y in common])[0, 1])


@dataclass
class LineProjection:
    line: str
    target_year: int
    severity_fit: TrendFit
    frequency_fit: TrendFit
    exposure: float
    cpi_factor: float
    freq_sev_corr: float

    @property
    def mu_log_severity(self):
        return float(self.severity_fit.fitted([self.target_year])[0] + np.log(self.cpi_factor))

    @property
    def mu_log_frequency(self):
        return float(self.frequency_fit.fitted([self.target_year])[0])

    @property
    def expected_severity(self):
        return float(np.exp(self.mu_log_severity + 0.5 * self.severity_fit.sigma**2))

    @property
    def expected_frequency(self):
        return float(np.exp(self.mu_log_frequency + 0.5 * self.frequency_fit.sigma**2))

    @property
    def expected_claims_count(self):
        return self.exposure * self.expected_frequency

    @property
    def expected_aggregate(self):
        cov = self.freq_sev_corr * self.frequency_fit.sigma * self.severity_fit.sigma
        return self.expected_claims_count * self.expected_severity * np.exp(cov)

def project_line(line, df=None, target_year=config.PROJECTION_YEAR):
    df = get_kpi_data() if df is None else df
    d = df[df["line"] == line].sort_values("year")
    sev, freq = fit_severity(d, line), fit_frequency(d, line)
    rho = (residual_correlation(freq, sev) if config.FREQ_SEV_CORRELATION is None
           else config.FREQ_SEV_CORRELATION)
    return LineProjection(line, target_year, sev, freq,
                          project_exposure(d, target_year),
                          cpi_projection_factor(df, target_year), rho)

def _simulate_log_value(fit, target_year, z, rng, parameter_uncertainty):
    x = fit.design([target_year])[0]
    n = len(z)
    if not parameter_uncertainty:
        return x @ fit.coef + fit.sigma * z
    sigma_draw = fit.sigma * np.sqrt(fit.dof / rng.chisquare(fit.dof, size=n))
    chol = np.linalg.cholesky(fit.xtx_inv)
    coef_draw = fit.coef + sigma_draw[:, None] * (
        rng.standard_normal((n, len(fit.coef))) @ chol.T)
    return coef_draw @ x + sigma_draw * z

def simulate_line(proj, n, rng, z_sev=None, z_freq=None,
                  parameter_uncertainty=config.INCLUDE_PARAMETER_UNCERTAINTY):
    z_sev = rng.standard_normal(n) if z_sev is None else z_sev
    if z_freq is None:
        rho = proj.freq_sev_corr
        z_freq = rho * z_sev + np.sqrt(1 - rho**2) * rng.standard_normal(n)

    log_freq = _simulate_log_value(proj.frequency_fit, proj.target_year, z_freq, rng, parameter_uncertainty)
    log_sev = _simulate_log_value(proj.severity_fit, proj.target_year, z_sev, rng, parameter_uncertainty)

    n_claims = rng.poisson(proj.exposure * np.exp(log_freq))
    severity = np.exp(log_sev) * proj.cpi_factor
    return {"claims": n_claims, "severity": severity, "aggregate": n_claims * severity}

def _risk_measures(x):
    mean = float(np.mean(x))
    var = float(np.quantile(x, config.VAR_LEVEL))
    return {"mean": mean, "var": var, "capital": var - mean,
            "capital_pct_of_mean": (var - mean) / mean}

def run_portfolio_monte_carlo(n_simulations=config.N_SIMULATIONS, seed=config.RANDOM_SEED,
                              parameter_uncertainty=config.INCLUDE_PARAMETER_UNCERTAINTY):
    rng = np.random.default_rng(seed)
    df = get_kpi_data()
    totals = np.zeros(n_simulations)
    lines = {}
    for line in config.LINES:
        proj = project_line(line, df)
        sim = simulate_line(proj, n_simulations, rng, parameter_uncertainty=parameter_uncertainty)
        totals += sim["aggregate"]
        lines[line] = {"projection": proj, "simulations": sim["aggregate"],
                       **_risk_measures(sim["aggregate"])}
    return {"total": totals, "lines": lines, **_risk_measures(totals)}

def compare_severity_distributions(line: str, df: pd.DataFrame | None = None) -> dict:
    """Is lognormal a reasonable choice for the year-to-year severity noise?

    Takes the ratio actual / trend for each year and fits a lognormal and a
    gamma to it, comparing AIC (lower = better). With only ~10-30 years the
    difference is usually small, which is itself worth reporting.
    Also runs a Shapiro-Wilk normality test on the log residuals
    (p > 0.05: no evidence against lognormal).
    """
    df = get_kpi_data() if df is None else df
    fit = fit_severity(df[df["line"] == line].sort_values("year"), line)
    ratio = np.exp(fit.residuals)

    ln_shape, _, ln_scale = stats.lognorm.fit(ratio, floc=0)
    g_shape, _, g_scale = stats.gamma.fit(ratio, floc=0)
    ll_ln = stats.lognorm.logpdf(ratio, ln_shape, 0, ln_scale).sum()
    ll_g = stats.gamma.logpdf(ratio, g_shape, 0, g_scale).sum()

    return {
        "n_years": len(ratio),
        "aic_lognormal": 2 * 2 - 2 * ll_ln,
        "aic_gamma": 2 * 2 - 2 * ll_g,
        "shapiro_p": float(stats.shapiro(fit.residuals).pvalue),
    }


def line_summary(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per line: fitted trends, volatilities and projection."""
    df = get_kpi_data() if df is None else df
    rows = []
    for line in config.LINES:
        p = project_line(line, df)
        d = df[df["line"] == line]
        rows.append({
            "line": line,
            "data_years": f"{d['year'].min()}-{d['year'].max()}",
            "trend_years": f"{p.severity_fit.years.min()}-{p.severity_fit.years.max()}",
            "superimposed_inflation": p.severity_fit.annual_growth,
            "superimposed_inflation_se": p.severity_fit.coef_se[1],
            "severity_sigma": p.severity_fit.sigma,
            "frequency_trend": p.frequency_fit.annual_growth,
            "frequency_sigma": p.frequency_fit.sigma,
            "freq_sev_corr": p.freq_sev_corr,
            "exposure_projected": p.exposure,
            "expected_claims_count": p.expected_claims_count,
            "expected_severity": p.expected_severity,
            "expected_aggregate": p.expected_aggregate,
            # Premium-weighted loss ratio = total claims / total premium
            "loss_ratio_weighted": d["claims_paid"].sum() / d["written_premium"].sum(),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
    print(line_summary().T, "\n")

    for pu in (False, True):
        r = run_portfolio_monte_carlo(parameter_uncertainty=pu)
        label = "process + parameter risk" if pu else "process risk only"
        print(f"[{label}] expected €{r['mean']/1e6:,.1f}M | "
              f"VaR99.5 €{r['var']/1e6:,.1f}M | capital €{r['capital']/1e6:,.1f}M "
              f"({r['capital_pct_of_mean']:.1%} of expected)")
        for line, v in r["lines"].items():
            print(f"    {line:8s} expected €{v['mean']/1e6:7.1f}M  capital €{v['capital']/1e6:6.1f}M "
                  f"({v['capital_pct_of_mean']:.1%})")
    print()
    for line in config.LINES:
        print(line, compare_severity_distributions(line))