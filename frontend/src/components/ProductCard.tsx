import type { Product } from '../lib/api';
import { ShoppingCart, Star, Truck, ExternalLink } from 'lucide-react';

interface Props {
  product: Product;
  onAdd: (productId: string) => void;
}

const STORE_COLORS: Record<string, string> = {
  Amazon: 'bg-orange-100 text-orange-800',
  Noon: 'bg-yellow-100 text-yellow-800',
  Jumia: 'bg-green-100 text-green-800',
};

export default function ProductCard({ product, onAdd }: Props) {
  const badge = STORE_COLORS[product.retailer] ?? 'bg-gray-100 text-gray-800';

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden hover:shadow-md transition-shadow flex flex-col">
      {/* Image */}
      <div className="h-40 bg-gray-100 flex items-center justify-center overflow-hidden">
        {product.image_url ? (
          <img
            src={product.image_url}
            alt={product.name}
            className="h-full w-full object-contain p-2"
          />
        ) : (
          <div className="text-4xl text-gray-300">📦</div>
        )}
      </div>

      <div className="p-4 flex flex-col flex-1 gap-2">
        {/* Store badge */}
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full w-fit ${badge}`}>
          {product.retailer}
        </span>

        {/* Title */}
        <h3 className="font-semibold text-sm leading-tight line-clamp-2" title={product.name}>
          {product.name}
        </h3>

        {/* Price */}
        <div className="text-lg font-bold text-brand-700">
          ${product.price_usd.toFixed(2)}
          {product.currency !== 'USD' && (
            <span className="text-xs text-gray-400 ml-1">
              ({product.price.toFixed(0)} {product.currency})
            </span>
          )}
        </div>

        {/* Meta row */}
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {product.rating && (
            <span className="flex items-center gap-0.5">
              <Star size={12} className="text-yellow-500 fill-yellow-500" />
              {product.rating.toFixed(1)}
            </span>
          )}
          {product.delivery_days && (
            <span className="flex items-center gap-0.5">
              <Truck size={12} />
              {product.delivery_days}d
            </span>
          )}
        </div>

        {/* Rank explanation */}
        {product.rank_explanation && (
          <p className="text-[11px] text-gray-400 leading-snug line-clamp-2 mt-auto">
            {product.rank_explanation}
          </p>
        )}

        {/* Actions */}
        <div className="flex gap-2 mt-2">
          <button
            onClick={() => onAdd(product.id)}
            className="flex-1 flex items-center justify-center gap-1.5 bg-brand-600 text-white text-sm font-medium rounded-lg py-2 hover:bg-brand-700 transition-colors"
          >
            <ShoppingCart size={14} />
            Add
          </button>
          {product.product_url && (
            <a
              href={product.product_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center px-3 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 transition-colors"
            >
              <ExternalLink size={14} />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
