import type { CartSummary } from '../lib/api';
import { Trash2, ShoppingBag } from 'lucide-react';

interface Props {
  cart: CartSummary | null;
  onRemove: (productId: string) => void;
  onCheckout: () => void;
}

export default function CartPanel({ cart, onRemove, onCheckout }: Props) {
  if (!cart || cart.items_count === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-100 p-6 text-center text-gray-400">
        <ShoppingBag size={32} className="mx-auto mb-2 opacity-50" />
        <p className="text-sm">Cart is empty</p>
        <p className="text-xs mt-1">Search for products and add them here</p>
      </div>
    );
  }

  const pct = Math.min(100, (cart.total_usd / cart.budget_usd) * 100);
  const barColor = pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-yellow-500' : 'bg-green-500';

  return (
    <div className="bg-white rounded-xl border border-gray-100 flex flex-col">
      {/* Header + budget bar */}
      <div className="p-4 border-b border-gray-50">
        <div className="flex justify-between text-sm font-medium mb-2">
          <span>Budget</span>
          <span>
            ${cart.total_usd.toFixed(2)} / ${cart.budget_usd.toFixed(2)}
          </span>
        </div>
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
        </div>
        <p className="text-xs text-gray-400 mt-1">
          ${cart.remaining_budget_usd.toFixed(2)} remaining
        </p>
      </div>

      {/* Items grouped by store */}
      <div className="flex-1 overflow-y-auto max-h-96 divide-y divide-gray-50">
        {Object.entries(cart.items_by_store).map(([store, items]) => (
          <div key={store} className="p-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              {store}
            </p>
            <ul className="space-y-2">
              {items.map((item) => (
                <li key={item.id} className="flex items-start gap-2 text-sm">
                  {item.image_url ? (
                    <img src={item.image_url} alt="" className="w-10 h-10 rounded object-contain bg-gray-50 flex-shrink-0" />
                  ) : (
                    <div className="w-10 h-10 rounded bg-gray-50 flex items-center justify-center text-lg flex-shrink-0">📦</div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{item.name}</p>
                    <p className="text-xs text-gray-400">
                      ${item.price_usd.toFixed(2)} x {item.quantity}
                    </p>
                  </div>
                  <button
                    onClick={() => onRemove(item.product_id)}
                    className="text-gray-300 hover:text-red-500 p-1 transition-colors flex-shrink-0"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-gray-100">
        <div className="flex justify-between font-semibold mb-3">
          <span>Total</span>
          <span>${cart.total_usd.toFixed(2)}</span>
        </div>
        <button
          onClick={onCheckout}
          className="w-full bg-brand-600 text-white font-medium rounded-lg py-2.5 hover:bg-brand-700 transition-colors"
        >
          Simulate Checkout ({cart.retailers.length} store{cart.retailers.length !== 1 ? 's' : ''})
        </button>
      </div>
    </div>
  );
}
