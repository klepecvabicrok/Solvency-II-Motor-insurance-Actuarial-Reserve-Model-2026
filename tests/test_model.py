"""
Checks that the model's maths does what it claims.
Run from the project root after `python database_setup.py`:
    pytest            (or:  python tests/test_model.py)
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402
import database_setup as ds  # noqa: E402
import model_engine as me  # noqa: E402


def test_trend_recovers_known_growth():
    years = np.arange(2000, 2020)
    values = 1000 * 1.04 ** (years - 2000)          # exactly 4% a year, no noise
    fit = me.fit_log_trend(years, values)
    assert abs(fit.annual_growth - 0.04) < 1e-10
    assert fit.sigma < 1e-10


def test_structural_break_is_captured():
    years = np.arange(2000, 2020)
    values = 1000 * 1.02 ** (years - 2000) * np.where(years >= 2010, 1.3, 1.0)
    fit = me.fit_log_trend(years, values, breaks=[2010])
    assert abs(fit.annual_growth - 0.02) < 1e-10
    assert abs(np.exp(fit.coef[2]) - 1.3) < 1e-10


def test_predictive_interval_coverage():
    """With parameter uncertainty, a 95% forecast interval should contain the
    true next-year value ~95% of the time, even with only 10 data points.
    (Plug-in intervals that ignore parameter risk fall short of 95%.)"""
    rng = np.random.default_rng(1)
    years = np.arange(2016, 2026)
    hits_param, hits_plugin, reps = 0, 0, 2000
    for _ in range(reps):
        log_y = 7 + 0.03 * (years - 2016) + 0.05 * rng.standard_normal(len(years))
        truth = 7 + 0.03 * 10 + 0.05 * rng.standard_normal()
        fit = me.fit_log_trend(years, np.exp(log_y))
        z = rng.standard_normal(4000)
        for pu in (True, False):
            sims = me._simulate_log_value(fit, 2026, z, rng, parameter_uncertainty=pu)
            lo, hi = np.quantile(sims, [0.025, 0.975])
            if lo <= truth <= hi:
                if pu:
                    hits_param += 1
                else:
                    hits_plugin += 1
    assert abs(hits_param / reps - 0.95) < 0.02
    assert hits_plugin / reps < hits_param / reps


def test_simulated_mean_matches_formula():
    """Without parameter risk the simulation mean must equal the closed-form
    E[N x S] (lognormal means + frequency/severity correlation)."""
    r = me.run_portfolio_monte_carlo(n_simulations=200_000, parameter_uncertainty=False)
    for line, res in r["lines"].items():
        assert abs(res["mean"] / res["projection"].expected_aggregate - 1) < 0.005, line


def test_cpi_rebased_to_last_year():
    monthly = pd.read_csv(config.CPI_CSV)
    cpi = ds.build_cpi_table(monthly)
    assert abs(cpi["cpi_index"].iloc[-1] - 1.0) < 1e-12
    # only complete years are kept
    monthly["year"] = monthly["date"].str[:4].astype(int)
    full_years = monthly.groupby("year").size().loc[lambda s: s == 12].index
    assert list(cpi["year"]) == list(full_years)


def test_validation_catches_bad_rows():
    bad = pd.DataFrame({"year": [2020, 2020], "line": ["AO", "AO"], "policies": [100, 100],
                        "claims": [5, -1], "written_premium": [1000, 1000], "claims_paid": [500, 500]})
    problems = ds.validate_claims(bad)
    assert any("negative" in p for p in problems)
    assert any("duplicate" in p for p in problems)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("passed", name)
