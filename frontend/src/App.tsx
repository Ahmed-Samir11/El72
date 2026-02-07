import { useState } from 'react';
import { useSession } from './hooks/useSession';
import SearchBar from './components/SearchBar';
import ProductCard from './components/ProductCard';
import CartPanel from './components/CartPanel';
import CheckoutView from './components/CheckoutView';
import SkeletonCard from './components/SkeletonCard';
import { ShoppingCart, Mic, MessageSquare } from 'lucide-react';
import type { CheckoutPlan } from './lib/api';

export default function App() {
  const {
    sessionId,
    cart,
    searchResults,
    loading,
    search,
    addToCart,
    removeFromCart,
    checkout,
  } = useSession();

  const [showCheckout, setShowCheckout] = useState<CheckoutPlan | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>('');

  const categories = Object.keys(searchResults);

  const handleSearch = async (query: string, category: string) => {
    await search(query, category);
    setActiveCategory(category || query);
  };

  const handleCheckout = async () => {
    const plan = await checkout();
    setShowCheckout(plan);
  };

  const visibleProducts = activeCategory
    ? searchResults[activeCategory] ?? []
    : categories.length > 0
      ? searchResults[categories[categories.length - 1]] ?? []
      : [];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-100 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🛒</span>
            <h1 className="text-lg font-bold tracking-tight">
              Cart<span className="text-brand-600">Pilot</span>
            </h1>
            <span className="text-xs text-gray-400 hidden sm:inline ml-2">
              Agentic Commerce
            </span>
          </div>

          <div className="flex items-center gap-3 text-sm text-gray-500">
            {sessionId && (
              <span className="text-xs bg-gray-100 px-2 py-1 rounded font-mono">
                {sessionId.slice(0, 8)}
              </span>
            )}
            {cart && cart.items_count > 0 && (
              <div className="flex items-center gap-1 font-medium text-brand-600">
                <ShoppingCart size={16} />
                {cart.items_count}
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6">
        {/* Hero / Voice prompt area */}
        <div className="bg-gradient-to-br from-brand-600 to-brand-700 rounded-2xl p-6 sm:p-8 text-white mb-6">
          <div className="flex items-start gap-4">
            <div className="flex-1">
              <h2 className="text-xl sm:text-2xl font-bold mb-2">
                What event are you planning?
              </h2>
              <p className="text-white/80 text-sm sm:text-base mb-4">
                Tell me what you need — I'll search real stores, compare prices, and build
                your cart. Try: <em>"I'm hosting a hackathon for 60 people, budget $500"</em>
              </p>

              {/* ElevenLabs widget placeholder */}
              <div className="flex items-center gap-3 bg-white/10 backdrop-blur rounded-xl px-4 py-3">
                <Mic size={20} className="text-white/60" />
                <span className="text-sm text-white/60">
                  ElevenLabs voice agent widget goes here — see elevenlabs_agent_config.md
                </span>
                <MessageSquare size={20} className="text-white/60 ml-auto" />
              </div>
            </div>
          </div>
        </div>

        {/* Search bar */}
        <div className="mb-6">
          <SearchBar onSearch={handleSearch} loading={loading} />
        </div>

        {/* Main grid: Products + Cart */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Products column (2/3) */}
          <div className="lg:col-span-2 space-y-4">
            {/* Category tabs */}
            {categories.length > 1 && (
              <div className="flex gap-2 overflow-x-auto pb-2">
                {categories.map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setActiveCategory(cat)}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${
                      (activeCategory || categories[categories.length - 1]) === cat
                        ? 'bg-brand-600 text-white'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}
                  >
                    {cat}
                    <span className="ml-1 opacity-60">
                      ({searchResults[cat]?.length ?? 0})
                    </span>
                  </button>
                ))}
              </div>
            )}

            {/* Product grid */}
            {loading && visibleProducts.length === 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <SkeletonCard key={i} />
                ))}
              </div>
            ) : visibleProducts.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
                {visibleProducts.map((p) => (
                  <ProductCard key={p.id} product={p} onAdd={addToCart} />
                ))}
              </div>
            ) : (
              <div className="text-center py-16 text-gray-400">
                <p className="text-lg mb-1">No products yet</p>
                <p className="text-sm">
                  Use the search bar or talk to the voice agent to find products
                </p>
              </div>
            )}
          </div>

          {/* Cart column (1/3) */}
          <div className="space-y-4">
            <CartPanel cart={cart} onRemove={removeFromCart} onCheckout={handleCheckout} />
          </div>
        </div>
      </main>

      {/* Checkout overlay */}
      {showCheckout && (
        <CheckoutView plan={showCheckout} onClose={() => setShowCheckout(null)} />
      )}
    </div>
  );
}
