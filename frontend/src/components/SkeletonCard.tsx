export default function SkeletonCard() {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="h-40 skeleton" />
      <div className="p-4 space-y-3">
        <div className="h-4 skeleton w-16" />
        <div className="h-4 skeleton w-3/4" />
        <div className="h-6 skeleton w-20" />
        <div className="h-3 skeleton w-full" />
        <div className="h-9 skeleton w-full mt-2" />
      </div>
    </div>
  );
}
