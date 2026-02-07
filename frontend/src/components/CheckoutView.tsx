import { useEffect, useState } from 'react';
import type { CheckoutPlan } from '../lib/api';
import { Check, Loader2, Package } from 'lucide-react';

interface Props {
  plan: CheckoutPlan;
  onClose: () => void;
}

export default function CheckoutView({ plan, onClose }: Props) {
  const [completed, setCompleted] = useState<Set<number>>(new Set());

  // Animate steps completing one by one
  useEffect(() => {
    let i = 0;
    const timer = setInterval(() => {
      if (i < plan.steps.length) {
        setCompleted((prev) => new Set(prev).add(plan.steps[i].step));
        i++;
      } else {
        clearInterval(timer);
      }
    }, 1200);
    return () => clearInterval(timer);
  }, [plan]);

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full max-h-[80vh] overflow-y-auto">
        <div className="p-6 border-b border-gray-100">
          <h2 className="text-xl font-bold">Checkout Simulation</h2>
          <p className="text-sm text-gray-400 mt-1">
            Total: ${plan.total_usd.toFixed(2)} &middot; {plan.estimated_delivery}
          </p>
        </div>

        <div className="p-6 space-y-4">
          {plan.steps.map((step) => {
            const done = completed.has(step.step);
            return (
              <div
                key={step.step}
                className={`flex gap-3 transition-opacity duration-500 ${done ? 'opacity-100' : 'opacity-40'}`}
              >
                <div
                  className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-colors ${
                    done ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-400'
                  }`}
                >
                  {done ? <Check size={16} /> : <Loader2 size={16} className="animate-spin" />}
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium">{step.action}</p>
                  {step.items.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {step.items.map((item, idx) => (
                        <li key={idx} className="text-xs text-gray-400 flex items-center gap-1">
                          <Package size={10} />
                          {item}
                        </li>
                      ))}
                    </ul>
                  )}
                  {step.subtotal_usd > 0 && (
                    <p className="text-xs text-gray-500 mt-1">Subtotal: ${step.subtotal_usd.toFixed(2)}</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="p-6 border-t border-gray-100">
          <button
            onClick={onClose}
            className="w-full bg-gray-900 text-white rounded-lg py-2.5 font-medium hover:bg-gray-800 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
