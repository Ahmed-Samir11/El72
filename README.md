# CartPilot — Agentic Commerce

> Talk to buy. An AI shopping agent that crawls real stores, ranks products, and builds a single cart across retailers.

**Hackathon project** for the Agentic Commerce VC Track.

---

## Architecture

```
User (voice/text)
       │
       ▼
┌─────────────────────────────┐
│  ElevenLabs Agents Platform │  ← Hosted: STT + LLM + TTS + turn-taking
│  (system prompt + tools)    │
└──────────┬──────────────────┘
           │ HTTP tool calls
           ▼
┌─────────────────────────────┐
│  FastAPI Backend             │  ← Our code
│  ├── Crawler Module          │     Crawl4AI (primary) + Playwright (fallback)
│  │   ├── Amazon Adapter      │
│  │   ├── Noon Adapter        │
│  │   └── Jumia Adapter       │
│  ├── Ranking Module          │     Weighted scoring: cost, delivery, coherence
│  ├── Cart Module             │     Multi-retailer combined cart
│  └── Checkout Module         │     Simulated multi-store checkout
└──────────┬──────────────────┘
           │ REST + WebSocket
           ▼
┌─────────────────────────────┐
│  React Frontend (Lovable)    │  ← Visual layer
│  ├── Voice Widget            │
│  ├── Product Grid            │
│  ├── Combined Cart           │
│  └── Checkout Simulation     │
└─────────────────────────────┘
```

## Key Features

| Feature | Implementation |
|---------|---------------|
| Conversational brief capture | ElevenLabs agent + system prompt |
| Multi-retailer discovery (3+) | Crawl4AI crawls Amazon, Noon, Jumia |
| Transparent ranking engine | Weighted scoring: cost (40%), delivery (30%), coherence (30%) |
| Combined cart view | In-memory cart grouped by retailer, budget tracking |
| Checkout orchestration | Simulated per-retailer checkout steps |
| Voice interaction | ElevenLabs STT + TTS (hosted) |

## Design Patterns

- **Strategy** — Retailer adapters and ranking scorers are pluggable
- **Adapter** — Crawl4AI and Playwright behind the same interface
- **Pipeline** — Intent → Crawl → Extract → Rank → Cart → Checkout
- **Observer** — WebSocket pushes real-time updates to the frontend

## Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt
crawl4ai-setup  # install headless browser
cp .env.example .env  # fill in OPENAI_API_KEY
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — the Vite proxy forwards API calls to the backend.

### ElevenLabs Agent

Follow the instructions in `backend/elevenlabs_agent_config.md` to set up the voice agent on the ElevenLabs dashboard.

## Tech Stack

- **Backend**: Python 3.11, FastAPI, Crawl4AI, Playwright (fallback), Pydantic v2
- **Frontend**: React 18, TypeScript, Tailwind CSS, Vite
- **Voice Agent**: ElevenLabs Agents Platform (hosted)
- **LLM**: OpenAI GPT-4o-mini (extraction), ElevenLabs-hosted LLM (conversation)

## What's Real vs Simulated

| Component | Real or Simulated |
|-----------|-------------------|
| Product data | **Real** — crawled live from stores |
| Prices | **Real** — extracted from actual listings |
| Ranking | **Real** — algorithmic weighted scoring |
| Cart | **Real** — tracks actual products + prices |
| Checkout | **Simulated** — no real purchases made |
| Payment | **Simulated** — form-fill preview only |

## Team

Built in 24 hours for the Agentic Commerce hackathon.
