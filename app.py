import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from model_engine import (
    calculate_severity_inflation,
    get_kpi_data,
    run_portfolio_monte_carlo,
)

st.set_page_config(
    page_title="Actuarial Model - Solvency II SZZ", layout="wide"
)

st.title("Solvency II Motor insurance Actuarial & Reserve Model 2026")
st.markdown(
    "Projection of Best Estimate Liabilities ($BEL$) and Solvency Capital Requirement ($SCR$) estimation at $VaR_{99.5\\%}$ "
    "based on SZZ historical data using **SQLite**, **Log-linear Regression**, and **Poisson-Lognormal Monte Carlo Simulations**."
)

st.divider()

st.sidebar.header("Simulation Settings")
n_sims = st.sidebar.slider("Number of Monte Carlo Simulations", 1000, 10000, 2000, step=1000)

line_map = {
    "AO": "MTPL (Motor Third-Party Liability)",
    "AO_PLUS": "AO+ (Driver Personal Accident)",
    "KASKO": "Comprehensive Motor (Kasko)",
}

selected_line_raw = st.sidebar.selectbox(
    "Select Line of Business",
    ["AO", "AO_PLUS", "KASKO"],
    format_func=lambda x: line_map[x],
)

@st.cache_data
def cached_simulation(sims):
    return run_portfolio_monte_carlo(n_simulations=sims)

exp_tot, var995, buffer, simulated_totals, line_details = cached_simulation(n_sims)

col1, col2, col3 = st.columns(3)
col1.metric("Expected Liabilities (BEL 2026)", f"€{exp_tot:,.2f}")
col2.metric("Value at Risk (VaR 99.5%)", f"€{var995:,.2f}")
col3.metric("Solvency Capital Requirement (SCR Buffer)", f"€{buffer:,.2f}", delta_color="inverse")

st.divider()

st.subheader(f"Historical Severity Trend: {line_map[selected_line_raw]}")
df_kpi = get_kpi_data()
subset = df_kpi[df_kpi["line"] == selected_line_raw].sort_values("year")

beta, alpha, inflation, std_error = calculate_severity_inflation(selected_line_raw)
t = np.arange(len(subset))
fitted_severity = np.exp(alpha + beta * t)

fig_trend = go.Figure()
fig_trend.add_trace(go.Scatter(x=subset["year"], y=subset["severity"], mode="markers+lines", name="Actual Average Severity (€)"))
fig_trend.add_trace(go.Scatter(x=subset["year"], y=fitted_severity, mode="lines", name=f"Exponential Trend (Inflation: {inflation:.2f}%)", line=dict(dash="dash", color="red")))

fig_trend.update_layout(xaxis_title="Year", yaxis_title="Average Severity (€)", template="plotly_white")
st.plotly_chart(fig_trend, use_container_width=True)

st.subheader("Stochastic Portfolio Loss Distribution (Solvency II SCR)")
fig_hist = px.histogram(x=simulated_totals, nbins=50, title=f"Distribution of {n_sims:,} Simulated Outcomes for 2026", color_discrete_sequence=["#2ca02c"])
fig_hist.add_vline(x=var995, line_dash="dash", line_color="red", annotation_text=f"VaR 99.5% (€{var995:,.0f})")
fig_hist.update_layout(xaxis_title="Aggregate Claims Paid (€)", yaxis_title="Frequency", template="plotly_white")
st.plotly_chart(fig_hist, use_container_width=True)