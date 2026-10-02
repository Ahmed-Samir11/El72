from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalyzerSettings(BaseSettings):
    # The repository uses one shared .env for several services. Ignore keys
    # owned by those other services when loading that dotenv file; process
    # environment values for declared analyzer settings remain validated.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    service_name: str = Field("analyzer", env="SERVICE_NAME")

    # Redis / Streams
    redis_url: str = Field(..., env="REDIS_URL")
    stream_price_ingest: str = Field("stream:price_ingest", env="STREAM_PRICE_INGEST")
    stream_confirmed: str = Field("stream:confirmed_deals", env="STREAM_CONFIRMED")
    consumer_group: str = Field("cg_analyzer", env="ANALYZER_GROUP")
    consumer_name: str = Field("analyzer-1", env="ANALYZER_CONSUMER")

    # Database
    database_url: str = Field(..., env="DATABASE_URL")
    timescale_url: Optional[str] = Field(None, env="TIMESCALE_URL")

    # ML
    ml_method: str = Field("mad", env="ML_METHOD")
    ml_threshold: float = Field(0.8, env="ANOMALY_THRESHOLD")
    model_dir: str = Field("models", env="MODEL_DIR")

    # Concurrency / performance
    concurrency: int = Field(4, env="SCRAPER_CONCURRENCY")
    consumer_count: int = Field(10, env="ANALYZER_CONSUMER_COUNT")
    scraper_nav_timeout_ms: int = Field(20000, env="SCRAPER_NAV_TIMEOUT_MS")

    # Misc
    xadd_retries: int = Field(3, env="XADD_RETRIES")
    xadd_backoff_s: float = Field(0.5, env="XADD_BACKOFF_S")
    ml_cpu_sample_interval: int = Field(5, env="ML_CPU_SAMPLE_INTERVAL")
    publish_batch_size: int = Field(20, env="PUBLISH_BATCH_SIZE")
    publish_batch_interval_s: float = Field(0.25, env="PUBLISH_BATCH_INTERVAL_S")
    publish_retry_attempts: int = Field(3, env="PUBLISH_RETRY_ATTEMPTS")
    publish_retry_backoff_s: float = Field(0.5, env="PUBLISH_RETRY_BACKOFF_S")
    dlq_stream: str = Field("stream:dlq:analyzer", env="DLQ_STREAM")
