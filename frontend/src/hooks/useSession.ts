import { useCallback, useEffect, useRef, useState } from 'react';
import type { CartSummary, Product, CheckoutPlan } from '../lib/api';
import * as api from '../lib/api';

/**
 * Manages session state + WebSocket connection.
 */
export function useSession() {
  const [sessionId, setSessionId] = useState('');
  const [cart, setCart] = useState<CartSummary | null>(null);
  const [searchResults, setSearchResults] = useState<Record<string, Product[]>>({});
  const [checkoutPlan, setCheckoutPlan] = useState<CheckoutPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [wsEvents, setWsEvents] = useState<Array<{ event: string; data: unknown }>>([]);
  const wsRef = useRef<WebSocket | null>(null);

  // ── WebSocket ──
  useEffect(() => {
    if (!sessionId) return;
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/${sessionId}`);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        setWsEvents((prev) => [...prev.slice(-50), { event: msg.event, data: msg }]);

        if (msg.event === 'cart_updated') {
          setCart(msg as CartSummary);
        }
      } catch {
        // ignore
      }
    };

    // Keep-alive ping every 25s
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 25_000);

    return () => {
      clearInterval(ping);
      ws.close();
    };
  }, [sessionId]);

  // ── Actions ──
  const search = useCallback(
    async (query: string, category: string) => {
      setLoading(true);
      try {
        const res = await api.searchProducts(query, category, sessionId);
        if (!sessionId && res.session_id) setSessionId(res.session_id);
        setSearchResults((prev) => ({ ...prev, [category || query]: res.products }));
        return res;
      } finally {
        setLoading(false);
      }
    },
    [sessionId],
  );

  const addToCart = useCallback(
    async (productId: string, qty = 1) => {
      const res = await api.addToCart(sessionId, productId, qty);
      setCart(res);
    },
    [sessionId],
  );

  const removeFromCart = useCallback(
    async (productId: string) => {
      const res = await api.removeFromCart(sessionId, productId);
      setCart(res);
    },
    [sessionId],
  );

  const checkout = useCallback(async () => {
    const plan = await api.simulateCheckout(sessionId);
    setCheckoutPlan(plan);
    return plan;
  }, [sessionId]);

  const refreshCart = useCallback(async () => {
    if (!sessionId) return;
    const c = await api.getCart(sessionId);
    setCart(c);
  }, [sessionId]);

  return {
    sessionId,
    setSessionId,
    cart,
    searchResults,
    checkoutPlan,
    loading,
    wsEvents,
    search,
    addToCart,
    removeFromCart,
    checkout,
    refreshCart,
  };
}
