from pydantic import BaseSettings, Field

class AnalyzerSettings(BaseSettings):
    service_name: str = Field("analyzer", env="SERVICE_NAME")

    # Redis / Streams
    redis_url: str = Field(..., env="REDIS_URL")
    stream_price_ingest: str = Field("stream:price_ingest", env="STREAM_PRICE_INGEST")
    stream_confirmed: str = Field("stream:confirmed_deals", env="STREAM_CONFIRMED")
    consumer_group: str = Field("cg_analyzer", env="ANALYZER_GROUP")
    consumer_name: str = Field("analyzer-1", env="ANALYZER_CONSUMER")

    # Database
    database_url: str = Field(..., env="DATABASE_URL")
    timescale_url: str = Field(None, env="TIMESCALE_URL")

    # ML
    ml_method: str = Field("mad", env="ML_METHOD")
    ml_threshold: float = Field(0.8, env="ANOMALY_THRESHOLD")
    model_dir: str = Field("models", env="MODEL_DIR")

    # Concurrency / performance
    concurrency: int = Field(4, env="SCRAPER_CONCURRENCY")
    consumer_count: int = Field(10, env="ANALYZER_CONSUMER_COUNT")

    # Browser / scraper-specific defaults (kept for parity)
    scraper_nav_timeout_ms: int = Field(20000, env="SCRAPER_NAV_TIMEOUT_MS")

    # Misc
    xadd_retries: int = Field(3, env="XADD_RETRIES")
    xadd_backoff_s: float = Field(0.5, env="XADD_BACKOFF_S")

    ml_cpu_sample_interval: int = Field(5, env="ML_CPU_SAMPLE_INTERVAL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
