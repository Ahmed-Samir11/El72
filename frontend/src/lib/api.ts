/**
 * Backend API client.
 *
 * All endpoints are relative — Vite proxy forwards to the FastAPI backend.
 */

const BASE = '';

export interface Product {
  id: string;
  name: string;
  price: number;
  currency: string;
  price_usd: number;
  image_url: string | null;
  product_url: string;
  retailer: string;
  delivery_days: number | null;
  rating: number | null;
  review_count: number | null;
  in_stock: boolean;
  category: string;
  rank_score: number;
  rank_explanation: string;
}

export interface CartSummary {
  session_id: string;
  items_count: number;
  total_usd: number;
  budget_usd: number;
  remaining_budget_usd: number;
  retailers: string[];
  items_by_store: Record<string, CartItemRaw[]>;
}

export interface CartItemRaw {
  id: string;
  product_id: string;
  name: string;
  price: number;
  currency: string;
  price_usd: number;
  quantity: number;
  retailer: string;
  image_url: string | null;
  product_url: string;
  delivery_days: number | null;
  category: string;
}

export interface CheckoutPlan {
  session_id: string;
  steps: CheckoutStep[];
  total_usd: number;
  estimated_delivery: string;
}

export interface CheckoutStep {
  step: number;
  retailer: string;
  action: string;
  items: string[];
  subtotal_usd: number;
  status: string;
}

export interface SessionState {
  session_id: string;
  spec: Record<string, unknown>;
  cart: CartSummary;
  search_results: Record<string, Product[]>;
}

// ── API calls ──────────────────────────────────────────────────────

export async function searchProducts(
  query: string,
  category: string,
  sessionId: string,
): Promise<{ session_id: string; products: Product[]; total_found: number }> {
  const res = await fetch(`${BASE}/tools/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, category, session_id: sessionId }),
  });
  return res.json();
}

export async function addToCart(
  sessionId: string,
  productId: string,
  quantity = 1,
): Promise<CartSummary> {
  const res = await fetch(`${BASE}/tools/cart/add`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, product_id: productId, quantity }),
  });
  return res.json();
}

export async function removeFromCart(
  sessionId: string,
  productId: string,
): Promise<CartSummary> {
  const res = await fetch(`${BASE}/tools/cart/remove`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, product_id: productId }),
  });
  return res.json();
}

export async function getCart(sessionId: string): Promise<CartSummary> {
  const res = await fetch(`${BASE}/tools/cart?session_id=${sessionId}`);
  return res.json();
}

export async function simulateCheckout(sessionId: string): Promise<CheckoutPlan> {
  const res = await fetch(`${BASE}/tools/checkout?session_id=${sessionId}`, {
    method: 'POST',
  });
  return res.json();
}

export async function getSession(sessionId: string): Promise<SessionState> {
  const res = await fetch(`${BASE}/session/${sessionId}`);
  return res.json();
}
