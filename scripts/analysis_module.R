# ==============================================================================
# Slovenian Motor Insurance Market: independent R check of historical data
# Recomputes loss ratios, frequency and real severity directly from SQLite,
# so the Python model's inputs can be cross-checked in a second language.
# Run from the project root:  Rscript scripts/analysis_module.R
# ==============================================================================

library(DBI)
library(RSQLite)
library(dplyr)
library(ggplot2)
library(scales)

# Keep these two in sync with config.py, so R checks the same data as Python:
DATA_END_YEAR    <- 2023  # config.DATA_END_YEAR: later years include foreign business
TREND_START_YEAR <- 2011  # config.SEVERITY_START_YEAR (2011 for every line)

conn <- dbConnect(RSQLite::SQLite(), "szz_market.db")
claims_raw <- dbGetQuery(conn, "
  SELECT c.*, p.cpi_index
  FROM szz_claims c
  LEFT JOIN cpi p ON p.year = c.year
")
dbDisconnect(conn)

claims_summary <- claims_raw %>%
  filter(year <= DATA_END_YEAR) %>%
  mutate(
    severity      = claims_paid / claims,
    real_severity = severity / cpi_index,
    frequency     = claims / policies,
    loss_ratio    = claims_paid / written_premium
  )

# Two ways to average a loss ratio over several years:
#  - simple mean of the yearly ratios gives every year equal weight
#  - premium-weighted (total claims / total premium) weights each year by its
#    size; this is the actuarial standard and is what the Python model reports.
summary_stats <- claims_summary %>%
  group_by(line) %>%
  summarise(
    data_years            = paste(min(year), max(year), sep = "-"),
    loss_ratio_weighted   = sum(claims_paid) / sum(written_premium),
    loss_ratio_simple_avg = mean(loss_ratio),
    total_premium         = sum(written_premium),
    total_claims_paid     = sum(claims_paid),
    # Log-linear trend of real severity over the trend window: slope ->
    # superimposed inflation. Should match model_engine.py's value.
    trend_years           = paste(TREND_START_YEAR, max(year), sep = "-"),
    superimposed_infl     = exp(coef(lm(log(real_severity[year >= TREND_START_YEAR]) ~
                                         year[year >= TREND_START_YEAR]))[2]) - 1,
    .groups = "drop"
  )

print(summary_stats, width = Inf)

year_breaks <- pretty(claims_summary$year)

p1 <- ggplot(claims_summary, aes(x = year, y = loss_ratio, color = line, group = line)) +
  geom_line(linewidth = 1.2) +
  geom_point(size = 2.5) +
  scale_y_continuous(labels = percent_format(accuracy = 1)) +
  scale_x_continuous(breaks = year_breaks) +
  labs(
    title = sprintf("Historical Loss Ratios (%d-%d)", min(claims_summary$year), max(claims_summary$year)),
    subtitle = "Source: Slovenian Insurance Association (SZZ)",
    x = "Year",
    y = "Loss ratio (claims paid / written premium)",
    color = "Line of business"
  ) +
  theme_minimal() +
  theme(legend.position = "bottom", plot.title = element_text(face = "bold"))

ggsave("loss_ratio_trend_R.png", plot = p1, width = 8, height = 5, dpi = 300)
