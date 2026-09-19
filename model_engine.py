import sqlite3
import numpy as np
import pandas as pd

def get_kpi_data():
    """Retrieves data from an SQLite database and calculates key actuarial metrics."""
    with sqlite3.connect("szz_market.db") as conn:
        query = """ 
        SELECT 
            year, 
            line, 
            policies, 
            claims, 
            written_premium, 
            claims_paid,
            ROUND(CAST(claims_paid AS FLOAT) / claims, 2) AS severity,
            ROUND(CAST(claims AS FLOAT) / policies, 4) AS frequency,
            ROUND(CAST(claims_paid AS FLOAT) / written_premium, 4) AS loss_ratio
        FROM szz_claims;
        """
        return pd.read_sql_query(query, conn)

def calculate_severity_inflation(line_name):
    """Calculate the annual inflation rate of claims using log-linear regression and volatility σ."""
    df = get_kpi_data()
    subset = df[df["line"] == line_name].sort_values("year")

    t = np.arange(len(subset))
    log_severity = np.log(subset["severity"])

    beta, alpha = np.polyfit(t, log_severity, 1)
    annual_inflation = (np.exp(beta) - 1) * 100

    fitted_log_severity = alpha + beta * t
    residuals = log_severity - fitted_log_severity
    std_error = np.std(residuals, ddof=2)

    return beta, alpha, annual_inflation, std_error

def project_line_2026(line_name):
    """Calculate the expected liability (BEL) using the log-normal model."""
    df = get_kpi_data()
    subset = df[df["line"] == line_name].sort_values("year")

    beta, alpha, _, std_error = calculate_severity_inflation(line_name)

    # 1. Direct log-mean projection (mu parameter for Lognormal distribution)
    projected_log_sev = alpha + beta * len(subset)
    
    # 2. Expected severity in EUR with convexity adjustment (E[X] = exp(mu + 0.5 * sigma^2))
    projected_severity_2026 = np.exp(projected_log_sev + 0.5 * std_error**2)

    latest_claims_count = subset["claims"].iloc[-1]
    bel_2026 = latest_claims_count * projected_severity_2026

    return latest_claims_count, projected_severity_2026, bel_2026, std_error, projected_log_sev


def run_portfolio_monte_carlo(n_simulations=2000, seed=42):
    """Running a stochastic Monte Carlo simulation in accordance with Solvency II standards (Lognormal + Poisson)."""
    np.random.seed(seed)
    lines = ["AO", "AO_PLUS", "KASKO"]

    simulated_totals = np.zeros(n_simulations)
    line_details = {}

    for line in lines:
        claims_exp, expected_sev, bel, sigma_log, mu_log = project_line_2026(line)

        # 1. Frequency Simulation (Poisson Distribution)
        sim_claims = np.random.poisson(lam=claims_exp, size=n_simulations)

        # 2. Simulation of Average Loss (Log-Normal Distribution) using direct mu_log
        sim_severity = np.random.lognormal(mean=mu_log, sigma=sigma_log, size=n_simulations)

        simulated_payouts = sim_claims * sim_severity
        simulated_totals += simulated_payouts

        line_details[line] = {
            "bel": bel,
            "volatility": sigma_log,
            "simulations": simulated_payouts,
        }

    expected_total = np.mean(simulated_totals)
    var_995 = np.percentile(simulated_totals, 99.5)  
    scr_buffer = var_995 - expected_total

    return expected_total, var_995, scr_buffer, simulated_totals, line_details