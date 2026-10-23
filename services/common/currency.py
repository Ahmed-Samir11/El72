"""Shared currency conversion constants.

Single source of truth for the approximate EGP/USD rate and the scraper's
currency->USD table. These are approximations for display/analytics, not a
financial feed (a live rate API should replace them in production).
"""

from __future__ import annotations

# 1 EGP ~= 0.032 USD (approximate).
EGP_TO_USD = 0.032

# Currency -> USD conversion rates.
EXCHANGE_RATES = {
    "USD": 1.0,
    "EGP": EGP_TO_USD,
    "AED": 0.27,  # UAE Dirham
    "SAR": 0.27,  # Saudi Riyal
}
