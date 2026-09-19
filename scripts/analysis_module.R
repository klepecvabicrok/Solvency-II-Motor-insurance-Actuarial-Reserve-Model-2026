# ==============================================================================
# Slovenian Auto Insurance Market Analysis (RSQLite + dplyr + ggplot2)
# Independent validation module for historical loss ratio trajectory
# ==============================================================================

library(DBI)
library(RSQLite)
library(dplyr)
library(ggplot2)
library(scales)

# Fetch market data from local SQLite repository
conn <- dbConnect(RSQLite::SQLite(), "szz_market.db")
claims_raw <- dbGetQuery(conn, "SELECT * FROM szz_claims")
dbDisconnect(conn)

# Calculate core actuarial KPIs: severity, frequency, and loss ratio
claims_summary <- claims_raw %>%
  mutate(
    severity = claims_paid / claims,
    frequency = claims / policies,
    loss_ratio = claims_paid / written_premium
  )

# Portfolio-level summary statistics grouped by line of business
summary_stats <- claims_summary %>%
  group_by(line) %>%
  summarise(
    avg_loss_ratio = mean(loss_ratio),
    total_premium = sum(written_premium),
    total_claims = sum(claims_paid)
  )

print(summary_stats)

# Plot historical loss ratio trajectory across lines of business
p1 <- ggplot(claims_summary, aes(x = year, y = loss_ratio, color = line, group = line)) +
  geom_line(linewidth = 1.2) +
  geom_point(size = 2.5) +
  scale_y_continuous(labels = percent_format(accuracy = 1)) +
  scale_x_continuous(breaks = seq(2016, 2025, by = 2)) +
  labs(
    title = "Historical Loss Ratio Trends (2016–2025)",
    subtitle = "Source: Slovenian Insurance Association (SZZ)",
    x = "Year",
    y = "Loss Ratio (Claims Paid / Written Premium)",
    color = "Line of Business"
  ) +
  theme_minimal() +
  theme(
    legend.position = "bottom",
    plot.title = element_text(face = "bold")
  )

# Export visualization for report integration
ggsave("loss_ratio_trend_R.png", plot = p1, width = 8, height = 5, dpi = 300)