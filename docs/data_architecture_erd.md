# El72 Data Architecture ERD

```mermaid
erDiagram
    USERS {
        uuid id PK
        string phone
        string status
        datetime deleted_at
    }
    ALERTS {
        uuid id PK
        uuid user_id FK
        string sku
    }
    DIM_PRODUCT {
        bigint product_key PK
        string source_product_id
        string name
    }
    DIM_RETAILER {
        bigint retailer_key PK
        string source_retailer_id
        string name
    }
    DIM_USER {
        bigint user_key PK
        uuid source_user_id
        string status
    }
    DIM_DATE {
        int date_key PK
        date full_date
        int year
        int month
        int day
    }
    DIM_TIME {
        int time_key PK
        int hour
        int minute
        int second
    }
    DIM_PROMOTION {
        bigint promotion_key PK
        string promotion_type
        decimal advertised_discount
    }
    DIM_CHANNEL {
        bigint channel_key PK
        string channel_name
    }
    FACT_PRICE_HISTORY {
        bigint price_history_key PK
        datetime observed_at PK
        bigint product_key FK
        bigint retailer_key FK
        int date_key FK
        int time_key FK
        bigint promotion_key FK
        decimal observed_price
        string source_sku
    }
    FACT_DEAL {
        bigint deal_key PK
        bigint product_key FK
        bigint retailer_key FK
        int date_key FK
        decimal current_price
        decimal historical_avg_price
        decimal historical_min_price
        decimal historical_max_price
        decimal deal_score
        string classification
        string model_version
    }
    FACT_NOTIFICATION {
        bigint notification_key PK
        bigint user_key FK
        bigint product_key FK
        bigint retailer_key FK
        int date_key FK
        bigint channel_key FK
        bigint deal_key FK
        string status
    }

    USERS ||--o{ ALERTS : owns
    DIM_PRODUCT ||--o{ FACT_PRICE_HISTORY : observed
    DIM_RETAILER ||--o{ FACT_PRICE_HISTORY : sold_by
    DIM_DATE ||--o{ FACT_PRICE_HISTORY : observed_on
    DIM_TIME ||--o{ FACT_PRICE_HISTORY : observed_at
    DIM_PROMOTION ||--o{ FACT_PRICE_HISTORY : advertised_as
    DIM_PRODUCT ||--o{ FACT_DEAL : evaluated
    DIM_RETAILER ||--o{ FACT_DEAL : offered_by
    DIM_DATE ||--o{ FACT_DEAL : detected_on
    DIM_PRODUCT ||--o{ FACT_NOTIFICATION : concerns
    DIM_RETAILER ||--o{ FACT_NOTIFICATION : from
    DIM_USER ||--o{ FACT_NOTIFICATION : receives
    DIM_DATE ||--o{ FACT_NOTIFICATION : sent_on
    DIM_CHANNEL ||--o{ FACT_NOTIFICATION : delivered_via
    FACT_DEAL ||--o{ FACT_NOTIFICATION : triggers
```

`USERS` and `ALERTS` are operational PostgreSQL entities. The dimensions and
facts are in the TimescaleDB `analytics` schema and map operational identifiers
through source columns rather than cross-database foreign keys.