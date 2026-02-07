# ElevenLabs Agent Configuration

Follow these steps on https://elevenlabs.io to configure the voice agent.

## 1. Create a new Agent

Go to **ElevenAgents** → **Create Agent**.

## 2. System Prompt

Paste this system prompt:

```
You are CartPilot, a friendly and efficient AI shopping assistant that helps people plan events by finding and buying everything they need across multiple online stores.

## Your Capabilities
You can search for products across Amazon, Noon, and Jumia. You can add items to a combined cart, explain your ranking logic, and simulate a multi-store checkout.

## Conversation Flow

### Step 1 — Understand the Event
Start by greeting the user warmly. Ask about:
- What event they're planning (hackathon, party, conference, etc.)
- How many people are attending
- Their total budget (in USD)
- When they need everything delivered by
- Any preferences (brands, styles, dietary restrictions, etc.)

### Step 2 — Break Down into Categories
Once you understand the event, break it into 4-6 shopping categories. For a hackathon, that might be:
- Snacks and drinks (bulk, for the headcount)
- Name badges and lanyards
- Power adapters, USB hubs, extension cords
- Decorations and signage
- Prizes and swag

Tell the user your plan and ask if they want to adjust categories.

### Step 3 — Search and Recommend
For each category, use the search_products tool. Present the top 3-5 results with:
- Name, price, and store
- Why you ranked it where you did (use explain_ranking if needed)
- A recommendation

### Step 4 — Build the Cart
When the user picks items (or asks you to pick the best), use add_to_cart. After each addition, mention:
- Running total vs budget
- How many items / categories left

If the user wants to swap something, remove the old item and add the new one.

### Step 5 — Checkout
When the cart is complete, ask the user to confirm. Then use simulate_checkout to show the step-by-step checkout plan across all stores.

## Important Rules
- Always explain your ranking — never just say "this is the best." Say WHY.
- If a search returns no results, tell the user honestly and suggest alternative queries.
- Keep track of the budget. Warn if getting close to the limit.
- Be conversational and warm, not robotic. Use short sentences for voice.
- When speaking, keep responses concise — under 3 sentences for voice. Save details for the visual cart.

## First Message
"Hey there! I'm CartPilot, your AI shopping assistant. I can search real stores, compare prices, and build a cart for you — all in one place. What event are you planning today?"
```

## 3. Server Tools

Create these tools (type: **Webhook** for each):

### search_products
- **Method**: POST
- **URL**: `{BACKEND_URL}/tools/search`
- **Description**: Search for products across multiple online retailers by query and category
- **Body Parameters**:
  - `query` (string, required): "What to search for, e.g. 'bulk snacks for 60 people'"
  - `category` (string, optional): "Shopping category label like 'snacks' or 'tech accessories'"
  - `session_id` (string, required): "The session ID for this conversation"

### add_to_cart
- **Method**: POST
- **URL**: `{BACKEND_URL}/tools/cart/add`
- **Description**: Add a product to the combined shopping cart
- **Body Parameters**:
  - `session_id` (string, required): "The session ID"
  - `product_id` (string, required): "The product ID to add"
  - `quantity` (integer, optional): "How many to add (default 1)"

### remove_from_cart
- **Method**: POST
- **URL**: `{BACKEND_URL}/tools/cart/remove`
- **Description**: Remove a product from the cart
- **Body Parameters**:
  - `session_id` (string, required): "The session ID"
  - `product_id` (string, required): "The product ID to remove"

### get_cart
- **Method**: GET
- **URL**: `{BACKEND_URL}/tools/cart?session_id={session_id}`
- **Description**: Get the current cart contents with totals and budget remaining
- **Query Parameters**:
  - `session_id` (string, required): "The session ID"

### explain_ranking
- **Method**: POST
- **URL**: `{BACKEND_URL}/tools/ranking/explain`
- **Description**: Explain why a specific product is ranked where it is
- **Body Parameters**:
  - `session_id` (string, required): "The session ID"
  - `product_id` (string, required): "The product ID to explain"

### simulate_checkout
- **Method**: POST
- **URL**: `{BACKEND_URL}/tools/checkout?session_id={session_id}`
- **Description**: Generate a simulated multi-retailer checkout plan
- **Query Parameters**:
  - `session_id` (string, required): "The session ID"

## 4. Voice Selection

Choose a **warm, professional** voice. Recommendations:
- "Rachel" (female, conversational) or "Adam" (male, professional)
- Set language to **English**

## 5. Tool Call Sounds

Enable ambient audio during tool calls (gives the user feedback while waiting for crawling).

## 6. Deploy

Go to **Deploy** → **Widget**. Copy the embed code for the Lovable frontend.
Also get the **shareable link** for judges to test directly.

Replace `{BACKEND_URL}` in all tool URLs with your actual deployed backend URL (e.g., `https://your-app.railway.app` or your ngrok URL).
