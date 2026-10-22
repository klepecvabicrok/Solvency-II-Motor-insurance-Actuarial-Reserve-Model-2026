"""
Step 7 helper: is a straight-line trend reasonable, and from which year?

For every line and both series (real severity, frequency) it prints two parts:

  A. ALL YEARS - the whole history. Shows the old regime changes, i.e. WHY
     the trends start later (config.SEVERITY_START_YEAR / FREQUENCY_START_YEAR).
     Breaks found here are expected; they are the reason for the start year,
     not something to add to the model.

  B. TREND WINDOW - only the years the model actually fits (from the start
     year on). This is the part to check: is there still a jump INSIDE the
     window? If a break here is flagged significant AND you can name its cause,
     add it to SEVERITY_BREAKS / FREQUENCY_BREAKS in config.py.

Breaks are tested with an F-test: does a step dummy in that year explain the
data significantly better than one straight line? Because many years are
tested, the 5% level is divided by the number of tests (Bonferroni).

It also saves breaks_<LINE>.png: data, the all-years line (grey, dashed) and
the trend the model uses (solid, from the start year, marked).

Run:  python explore_breaks.py
Nothing here changes the model. You read the output, decide, and write the
decision into config.py.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

import config
import model_engine as me

MIN_SEGMENT = 4   # a break needs at least 4 years on each side to be testable


def break_f_test(years, values, break_year):
    """F-test: trend without break vs trend with a step dummy at break_year.
    Returns (p-value, jump size). Small p = the jump is unlikely to be noise."""
    base = me.fit_log_trend(years, values)
    alt = me.fit_log_trend(years, values, breaks=[break_year])
    rss_base = np.sum(base.residuals ** 2)
    rss_alt = np.sum(alt.residuals ** 2)
    f = (rss_base - rss_alt) / (rss_alt / alt.dof)
    p = 1 - stats.f.cdf(f, 1, alt.dof)
    return p, np.exp(alt.coef[2]) - 1


def scan_breaks(years, values):
    """Test every candidate year; most significant first."""
    years = np.asarray(years)
    candidates = range(years.min() + MIN_SEGMENT, years.max() - MIN_SEGMENT + 2)
    results = [(b, *break_f_test(years, values, b)) for b in candidates]
    return sorted(results, key=lambda r: r[1])


def report(label, sub, col):
    """Print trend and the three most likely breaks for one slice of data."""
    fit = me.fit_log_trend(sub["year"], sub[col])
    print(f"    {label:24s} trend {fit.annual_growth:+.2%} a year, sigma {fit.sigma:.3f}, "
          f"{len(sub)} years")
    if len(sub) < 2 * MIN_SEGMENT + 1:
        print("      too few years to test for breaks")
        return fit
    scan = scan_breaks(sub["year"], sub[col])
    threshold = 0.05 / len(scan)
    for b, p, jump in scan[:3]:
        flag = "  <-- significant" if p < threshold else ""
        print(f"      break {b}: jump {jump:+.1%}, p = {p:.5f}{flag}")
    return fit


def main():
    df = me.get_kpi_data()
    for line in config.LINES:
        d = df[df["line"] == line].sort_values("year")
        sev = d.dropna(subset=["real_severity"])
        freq = d.dropna(subset=["frequency"])
        freq = freq[~freq["year"].isin(config.FREQUENCY_EXCLUDED_YEARS)]

        series = [
            ("Real severity (2025 €)", sev, "real_severity",
             config.SEVERITY_START_YEAR.get(line) or config.TREND_START_YEAR),
            ("Claim frequency", freq, "frequency",
             config.FREQUENCY_START_YEAR.get(line) or config.TREND_START_YEAR),
        ]

        print(f"\n=== {line} (data {d['year'].min()}-{d['year'].max()}) ===")
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
        for ax, (title, sub, col, start) in zip(axes, series):
            window = sub if start is None else sub[sub["year"] >= start]
            print(f"  {title}")
            full_fit = report("A. all years", sub, col)
            used_fit = report(f"B. trend window {window['year'].min()}+", window, col)

            ax.plot(sub["year"], sub[col], "o-", color="#888", lw=1, ms=4, label="data")
            ax.plot(sub["year"], np.exp(full_fit.fitted(sub["year"])), "--",
                    color="#bbb", label="all-years line")
            ax.plot(window["year"], np.exp(used_fit.fitted(window["year"])), "-",
                    color="#1f5fbf", lw=2.5, label="trend used by the model")
            if start is not None:
                ax.axvline(start, color="#1f5fbf", ls=":", lw=1)
            ax.set_yscale("log")
            ax.set_title(f"{line}: {title}")
            ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(f"breaks_{line}.png", dpi=120)
        plt.close(fig)

    print("\nPart A breaks explain the start year. Act only on part B breaks "
          "with a named cause.\nCharts saved as breaks_<LINE>.png")


if __name__ == "__main__":
    main()
