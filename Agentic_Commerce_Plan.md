Agentic Commerce — Automate the process of finding and buying things online 
VC Track

1. Goals / Motivation
Do you know that feeling of jumping from website to website, comparing prices, delivery times, and options — and then doing checkout after checkout?
We hate it too.
Whether you’re planning a party, buying an outfit, or organizing an event, online shopping today is:
fragmented
time-consuming
repetitive
and unnecessarily complex
Search engines help you find products — but they don’t help you get everything bought.
Goal: Build a conversational, agentic shopping experience that lets users describe what they want — and delegates the entire buying process to an AI agent.
Goal
Create an AI agent that can:
Understand a high-level shopping intent
Break it down into concrete shopping needs
Discover and rank products across multiple retailers
Create a single, combined cart
Orchestrate a cross-store checkout flow (simulated / sandboxed)
This is not a recommendation chatbot.
This is end-to-end agentic commerce.

Choose one scenario to keep the scope feasible in 24 hours.
Option A: Super Bowl Party Outfit
“I need a full outfit (head-to-toe) in team style, budget $150, delivered by Friday.”
Option B: Skiing Outfit
“Downhill skiing outfit, warm and waterproof, size M, budget $400, delivery within 5 days.”
Option C: Hackathon Host Kit
“I’m hosting a hackathon for 60 people — figure out what I need (snacks, badges, adapters, decorations, prizes) and buy it at the best price.”

2. Features
2.1 Conversational Brief & Constraints Capture
The agent must capture:
Budget
Delivery deadline
Preferences (style, size, brand, color)
Must-haves vs nice-to-haves
Output: a structured shopping spec (e.g. JSON).
2.2 Multi-Retailer Discovery (≥ 3 retailers)
The agent must source products from at least three different retailers, using:
real product data, or
mocked retailer APIs with realistic data
Each item must include:
price
delivery estimate
variants
retailer identity
2.3 Ranking Engine (Not Just LLM Output)
Products must be ranked using a transparent scoring logic, e.g.:
total cost
delivery feasibility
preference match
set coherence
The agent must explain:
“Why is this option ranked #1?”
2.4 Single Combined Cart View
Build a cart that:
combines items from multiple retailers
shows total cost and delivery per item
allows easy replacement or optimization
2.5 Checkout Orchestration (Safe Demo)
No real purchases required.
Allowed:
simulated checkout with form-fill replay
sandbox checkout + mocks
step-by-step checkout plan with autofill preview
Must show:
payment + address entered once
agent fans out checkout steps per retailer (simulated)
3. Constraints (Very Important)
No simple recommendation chatbot
No single-retailer solution
Combined cart UI is required
At least 3 retailers
Checkout must be simulated or sandboxed
User can modify the cart and the agent adapts

4. Optional Extensions (Stretch Goals)
 Budget optimizer (“same setup, cheaper”)
 Delivery optimizer (“everything arrives by Friday”)
 Style or category coherence
 Return-aware ranking
 Explain mode (decision trace)
4. Why Does It Matter?
The future of commerce isn’t more filters or better search.
It’s delegation.
This challenge explores a world where:
users describe outcomes, not SKUs
AI handles the complexity
and buying becomes a single, coherent experience
