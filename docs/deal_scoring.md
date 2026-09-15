# Deal Quality Scoring

`services/analyzer/deal_scorer.py` provides deterministic, explainable intelligence calculations. It is deliberately separate from the existing anomaly detector: anomaly scoring identifies unusual observations, while deal scoring estimates whether the observation is valuable to a buyer. Suspicious-discount analysis lives in `services/analyzer/fake_discount.py` and is reused by the scorer.

## Deal score

The score is bounded from 0 to 100:

- Historical discount: up to 35 points, based on the current price versus the historical median, capped at a 30% discount.
- Historical percentile: up to 25 points for being near the bottom of the observed price distribution.
- Cross-store advantage: up to 20 points, based on the current price versus the supplied competitor average, capped at a 15% advantage.
- Historical low: 15 points when the current price is within 0.5% of the observed minimum.
- Discount duration: up to 5 points for a discount observed over seven or more days.
- Suspicious-discount penalty: up to 30 points based on the fake-discount confidence signal.

Grades are:

```text
80-100  Excellent
60-79   Good
40-59   Fair
20-39   Weak
0-19    No deal
```

The result includes the score, grade, explanation strings, and raw signals such as historical median, percentile, volatility, cross-store advantage, historical-low status, and suspicious-discount output.

## Suspicious discounts

`detect_fake_discount` is a signal, not a legal fraud determination. It increases confidence when:

- An advertised reference price is at least 10% above the historical median.
- The current price is less than 8% below the historical median despite that reference price.
- Competitors are at least 3% cheaper on average.
- The current price is not near the historical minimum.
- A supplied recent-price sequence shows a spike of at least 10% above the historical median.

It returns `is_suspicious`, a bounded confidence value, reasons, and supporting signals.
