# Elhaq - Real-Time Price Tracking & Deal Detection Platform

[![CI](https://github.com/your-org/elhaq/workflows/CI/badge.svg)](https://github.com/your-org/elhaq/actions)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Elhaq is a sophisticated event-driven microservices platform designed for real-time price monitoring, anomaly detection, and intelligent deal notifications in the Egyptian market. Built with reliability and scalability in mind, it leverages Redis Streams for event-driven communication, machine learning for deal detection, and WhatsApp for user notifications.

## 🏗️ Architecture Overview

Elhaq follows a **microservices architecture** with **event-driven communication** using Redis Streams. The system is designed for high reliability with consumer groups, dead-letter handling, and comprehensive observability.

### Core Components

| Service | Technology | Purpose | Communication |
|---------|------------|---------|---------------|
| **API Gateway** | FastAPI (Python) | User authentication, alert management, public API | REST API |
| **Scraper** | Playwright (Python) | Price data collection from e-commerce sites | `stream:price_ingest` |
| **Analyzer** | FastAPI + ML (Python) | Data processing, anomaly detection, analytics | Consumer: `cg_analyzer` |
| **Notification** | Node.js/TypeScript | WhatsApp alert delivery | Consumer: `cg_notifier` |
| **Billing** | FastAPI (Python) | Payment processing, dynamic pricing | Webhooks |
| **Common** | Shared utilities | Redis client, Paymob integration | Library |

### Data Flow

```mermaid
graph TD
    A[Scraper] -->|XADD| B[stream:price_ingest]
    B -->|XREADGROUP| C[Analyzer]
    C -->|Persist| D[(TimescaleDB)]
    C -->|ML Scoring| E{Anomaly?}
    E -->|Yes| F[XADD stream:confirmed_deals]
    F -->|XREADGROUP| G[Notification]
    G -->|WhatsApp API| H[User Alerts]
    C -->|Analytics| I[(PostgreSQL)]
```

### Technology Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy
- **Frontend API**: RESTful with JWT authentication
- **Database**: PostgreSQL (users/alerts), TimescaleDB (time-series prices)
- **Cache/Streams**: Redis with Streams and Consumer Groups
- **ML**: scikit-learn Isolation Forest for anomaly detection
- **Scraping**: Playwright with proxy rotation
- **Notifications**: 360dialog WhatsApp Business API
- **Payments**: Paymob integration with HMAC validation
- **Infrastructure**: Docker Compose, Dockerfiles
- **Testing**: pytest (Python), Jest (TypeScript)
- **Documentation**: Sphinx
- **CI/CD**: GitHub Actions

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- Node.js 18+ (for notification service)
- Git

### Local Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/elhaq.git
   cd elhaq
   ```

2. **Environment Configuration**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start Infrastructure**
   ```bash
   docker-compose up -d redis postgres timescaledb
   ```

4. **Run Services**
   ```bash
   # Option A: Docker Compose (recommended)
   docker-compose up --build

   # Option B: Individual services
   # API Gateway
   cd services/api && pip install -r requirements.txt && uvicorn main:app --reload --port 8000

   # Analyzer
   cd services/analyzer && pip install -r requirements.txt && uvicorn app:app --reload --port 8001

   # Notification
   cd services/notification && npm install && npm run dev

   # Billing
   cd services/billing && pip install -r requirements.txt && uvicorn main:app --reload --port 8002
   ```

5. **Verify Setup**
   ```bash
   # Check API health
   curl http://localhost:8000/health

   # Check analyzer health
   curl http://localhost:8001/health

   # View logs
   docker-compose logs -f
   ```

## 🧪 Testing

Elhaq includes comprehensive unit and integration tests with 97%+ coverage.

### Run All Tests

```bash
# Python services
pytest

# With coverage
pytest --cov=services --cov-report=html

# TypeScript service
cd services/notification && npm test

# Integration tests
pytest tests/e2e_test.py
```

### Test Structure

- **Unit Tests**: 153 passing tests across all services
- **Integration Tests**: End-to-end stream processing validation
- **Mocking**: httpx for API calls, in-memory SQLite for DB isolation
- **Coverage**: HTML reports in `htmlcov/`

## 📚 Documentation

### API Documentation

- **API Gateway**: http://localhost:8000/docs (Swagger UI)
- **Analyzer**: http://localhost:8001/docs
- **Billing**: http://localhost:8002/docs

### Sphinx Documentation

```bash
pip install -r requirements.txt
sphinx-build -b html docs docs/_build/html
open docs/_build/html/index.html
```

## 🔧 Development

### Project Structure

```
elhaq/
├── services/
│   ├── api/           # User API & Authentication
│   ├── analyzer/      # ML Processing & Analytics
│   ├── billing/       # Payment Processing
│   ├── common/        # Shared Utilities
│   ├── notification/  # WhatsApp Notifications
│   └── scraper/       # Price Scraping
├── infra/
│   ├── monitoring/    # Prometheus, Alertmanager
│   └── sql/          # Database schemas
├── tests/             # Integration tests
├── docs/             # Sphinx documentation
└── docker-compose.yml
```

### Key Files

- `services/common/redis_client.py` - Async Redis Streams wrapper
- `services/analyzer/ml_detector.py` - Isolation Forest anomaly detection
- `services/analyzer/intent_upsert.py` - Analytics aggregation
- `infra/sql/ddl.sql` - TimescaleDB hypertables
- `infra/sql/alerts.sql` - PostgreSQL schemas

### Development Workflow

1. **Create Feature Branch**
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Run Tests**
   ```bash
   pytest services/your-service/
   ```

3. **Lint & Format**
   ```bash
   # Python
   black services/
   ruff services/

   # TypeScript
   cd services/notification && npm run lint
   ```

4. **Commit Changes**
   ```bash
   git add .
   git commit -m "feat: add your feature"
   ```

## 🚢 Deployment

### Docker Deployment

```bash
# Build all services
docker-compose build

# Deploy to production
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://user:pass@localhost/elhaq` |
| `TIMESCALE_URL` | TimescaleDB connection | `postgresql://user:pass@localhost/elhaq_ts` |
| `JWT_SECRET` | JWT signing key | `your-secret-key` |
| `PAYMOB_HMAC` | Paymob webhook secret | `hmac-secret` |
| `WHATSAPP_TOKEN` | 360dialog API token | `wa-token` |

### Production Considerations

- **Secrets Management**: Use Vault/KeyVault for secrets
- **TLS**: Enable Redis/PostgreSQL TLS
- **Monitoring**: Prometheus metrics, health checks
- **Scaling**: Redis Cluster, DB read replicas
- **Backups**: Automated DB backups, Redis persistence

## 🔍 Monitoring & Observability

### Health Checks

- `/health` - Service health status
- `/ready` - Readiness for traffic
- `/metrics` - Prometheus metrics

### Logging

- Structured JSON logging with `trace_id`
- Service-specific log levels
- Centralized log aggregation

### Alerts

- Stream backlog monitoring
- Error rate thresholds
- ML model drift detection
- Payment webhook failures

## 🤝 Contributing

### Development Setup

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

### Code Standards

- **Python**: Black formatting, Ruff linting
- **TypeScript**: ESLint, Prettier
- **Commits**: Conventional commits
- **Tests**: 80%+ coverage requirement

### Pull Request Process

1. Update documentation for API changes
2. Add migration scripts for DB changes
3. Update tests for new features
4. Ensure CI passes
5. Request review from maintainers

## 📋 Roadmap

### MVP Phase 1 (Current)
- ✅ User authentication & alerts API
- ✅ Robust price scraping infrastructure
- ✅ ML-based deal detection
- ✅ WhatsApp notifications

### Phase 2 (Next)
- 🔄 Billing & payment integration
- 🔄 Advanced analytics dashboard
- 🔄 Mobile app companion
- 🔄 Multi-language support

### Future Enhancements
- Real-time price alerts
- Advanced ML models (LSTM, GANs)
- Multi-region deployment
- API rate limiting & throttling

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with FastAPI, Redis, and modern Python practices
- Inspired by real-time data processing challenges
- Designed for the Egyptian e-commerce ecosystem

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/your-org/elhaq/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/elhaq/discussions)
- **Documentation**: [Read the Docs](https://elhaq.readthedocs.io/)

---

**Elhaq** - Turning price chaos into deal clarity 🚀
