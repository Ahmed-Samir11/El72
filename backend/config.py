"""
Application configuration loaded from environment variables.
"""

import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Central configuration — reads from .env or environment."""

    # --- API Keys ---
    openai_api_key: str = ""
    elevenlabs_api_key: str = ""

    # --- Crawl4AI ---
    crawl4ai_llm_provider: str = "openai/gpt-4o-mini"
    crawl4ai_timeout_seconds: int = 30
    crawl4ai_max_products_per_store: int = 8

    # --- Ranking weights (sum to 1.0) ---
    ranking_weight_cost: float = 0.40
    ranking_weight_delivery: float = 0.30
    ranking_weight_coherence: float = 0.30

    # --- Session ---
    default_budget_usd: float = 500.0
    default_deadline_days: int = 5

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: str = "*"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
