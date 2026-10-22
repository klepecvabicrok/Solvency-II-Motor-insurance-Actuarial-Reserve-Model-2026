import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import os

import config
import database_setup
import model_engine as me

# On Streamlit Cloud only the repository files exist, so build the database
# from the CSV files on first start if it is not there yet.
if not os.path.exists(config.DB_PATH):
    database_setup.build_database()

st.set_page_config(page_title="Slovenian Motor Premium Risk Model", layout="wide")

st.title("Slovenian Motor Insurance: Premium Risk Model")
st.markdown(
    f"Expected market claims for **{config.PROJECTION_YEAR}** and the capital needed for "
    f"**premium risk** at $VaR_{{99.5\\%}}$, from SZZ market data. "
    "Severity is modelled in real terms (CPI-deflated) with a separate general-inflation "
    "assumption; claim counts use a mixed Poisson model; trend-parameter uncertainty is included."
)
st.caption(
    "Market-level study, not an insurer's Solvency II balance sheet: the expected value is "
    "next year's claims, not a Best Estimate Liability, and the capital covers premium risk only."
)

# ---------------------------------------------------------------------------
# Sidebar: assumptions
# ---------------------------------------------------------------------------
st.sidebar.header("Assumptions")
n_sims = st.sidebar.slider("Monte Carlo simulations", 2_000, 50_000, config.N_SIMULATIONS, step=2_000)
cpi_infl = st.sidebar.slider(
    f"General inflation (CPI) to {config.PROJECTION_YEAR}, %",
    -1.0, 10.0, config.CPI_INFLATION_PROJECTION * 100, step=0.5,
) / 100
param_unc = st.sidebar.checkbox(
    "Include parameter uncertainty", value=config.INCLUDE_PARAMETER_UNCERTAINTY,
    help="Each simulation draws its own trend coefficients, reflecting that "
         "the trends are estimated from a limited number of years.",
)
selected_line = st.sidebar.selectbox("Line for detail charts", config.LINES,
                                     format_func=lambda x: config.LINE_NAMES[x])


@st.cache_data
def simulate(n, cpi, pu):
    config.CPI_INFLATION_PROJECTION = cpi
    r = me.run_portfolio_monte_carlo(n_simulations=n, parameter_uncertainty=pu)
    # keep only cache-friendly parts
    lines = {k: {kk: vv for kk, vv in v.items() if kk != "projection"} for k, v in r["lines"].items()}
    return r["mean"], r["var"], r["capital"], r["total"], lines


@st.cache_data
def summary(cpi):
    config.CPI_INFLATION_PROJECTION = cpi
    return me.line_summary()


exp_tot, var995, capital, totals, line_res = simulate(n_sims, cpi_infl, param_unc)

c1, c2, c3 = st.columns(3)
c1.metric(f"Expected claims {config.PROJECTION_YEAR}", f"€{exp_tot/1e6:,.1f}M")
c2.metric("VaR 99.5%", f"€{var995/1e6:,.1f}M")
c3.metric("Premium-risk capital (VaR − expected)", f"€{capital/1e6:,.1f}M",
          f"{capital/exp_tot:.1%} of expected", delta_color="off")

# ---------------------------------------------------------------------------
# Per-line table
# ---------------------------------------------------------------------------
st.subheader("By line of business")
s = summary(cpi_infl).set_index("line")
table = pd.DataFrame({
    "Expected claims (€M)": [line_res[l]["mean"] / 1e6 for l in s.index],
    "Capital (€M)": [line_res[l]["capital"] / 1e6 for l in s.index],
    "Capital % of expected": [line_res[l]["capital_pct_of_mean"] for l in s.index],
    "Superimposed inflation p.a.": s["superimposed_inflation"],
    "Frequency trend p.a.": s["frequency_trend"],
    "Severity σ": s["severity_sigma"],
    "Frequency σ": s["frequency_sigma"],
    "Freq–sev correlation": s["freq_sev_corr"],
    "Paid loss ratio (premium-weighted)": s["loss_ratio_weighted"],
}, index=[config.LINE_NAMES[l] for l in s.index])
st.dataframe(table.style.format({
    "Expected claims (€M)": "{:,.1f}", "Capital (€M)": "{:,.1f}",
    "Capital % of expected": "{:.1%}", "Superimposed inflation p.a.": "{:+.2%}",
    "Frequency trend p.a.": "{:+.2%}", "Severity σ": "{:.3f}", "Frequency σ": "{:.3f}",
    "Freq–sev correlation": "{:+.2f}", "Paid loss ratio (premium-weighted)": "{:.1%}",
}), use_container_width=True)
st.caption(
    "The capital of the portfolio is less than the sum of the lines (diversification). "
    "Lines are currently simulated independently, which overstates diversification; "
    "correlation between lines is the next upgrade."
)

# ---------------------------------------------------------------------------
# Trend charts for the selected line
# ---------------------------------------------------------------------------
df = me.get_kpi_data()
d = df[df["line"] == selected_line].sort_values("year")
config.CPI_INFLATION_PROJECTION = cpi_infl
proj = me.project_line(selected_line, df)
fit_years = np.arange(d["year"].min(), config.PROJECTION_YEAR + 1)

left, right = st.columns(2)

with left:
    st.markdown(f"**Severity: {config.LINE_NAMES[selected_line]}**")
    base_year = int(df.loc[df["cpi_index"].notna(), "year"].max())
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["year"], y=d["severity"], mode="markers+lines", name="Nominal severity"))
    fig.add_trace(go.Scatter(x=d["year"], y=d["real_severity"], mode="markers+lines",
                             name=f"Real severity ({base_year} €)"))
    fig.add_trace(go.Scatter(
        x=fit_years, y=np.exp(proj.severity_fit.fitted(fit_years)), mode="lines",
        name=f"Real trend ({proj.severity_fit.annual_growth:+.2%} p.a.)", line=dict(dash="dash"),
    ))
    fig.add_trace(go.Scatter(x=[config.PROJECTION_YEAR], y=[proj.expected_severity], mode="markers",
                             marker=dict(size=12, symbol="diamond"),
                             name=f"Expected {config.PROJECTION_YEAR} (nominal)"))
    fig.update_layout(xaxis_title="Year", yaxis_title="€ per claim", template="plotly_white",
                      legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.markdown(f"**Claim frequency: {config.LINE_NAMES[selected_line]}**")
    excluded = d["year"].isin(config.FREQUENCY_EXCLUDED_YEARS)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["year"], y=d["frequency"], mode="markers+lines", name="Frequency"))
    if excluded.any():
        fig.add_trace(go.Scatter(x=d.loc[excluded, "year"], y=d.loc[excluded, "frequency"], mode="markers",
                                 marker=dict(size=12, symbol="x"), name="Excluded from trend"))
    fig.add_trace(go.Scatter(
        x=fit_years, y=np.exp(proj.frequency_fit.fitted(fit_years)), mode="lines",
        name=f"Trend ({proj.frequency_fit.annual_growth:+.2%} p.a.)", line=dict(dash="dash"),
    ))
    fig.update_layout(xaxis_title="Year", yaxis_title="Claims per exposure unit (policy; registered car for Kasko)", template="plotly_white",
                      legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Loss distribution
# ---------------------------------------------------------------------------
st.subheader(f"Simulated market claims {config.PROJECTION_YEAR}")
fig = px.histogram(x=totals / 1e6, nbins=60)
fig.add_vline(x=exp_tot / 1e6, line_dash="dot", annotation_text="Expected")
fig.add_vline(x=var995 / 1e6, line_dash="dash", line_color="red", annotation_text="VaR 99.5%")
fig.update_layout(xaxis_title="Aggregate claims (€M)", yaxis_title="Simulations",
                  template="plotly_white", showlegend=False)
st.plotly_chart(fig, use_container_width=True)
