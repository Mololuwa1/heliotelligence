const TARGET_PR = 86.56;

export default function PRChip({ value, showDelta = true }) {
  if (value == null) {
    return <span className="font-mono text-slate-500 text-sm">—</span>;
  }

  const pct = (value * 100).toFixed(1);
  const delta = (value * 100 - TARGET_PR).toFixed(1);
  const positive = parseFloat(delta) >= 0;

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="font-mono text-amber-400 font-semibold">{pct}%</span>
      {showDelta && (
        <span
          className={`text-xs font-mono px-1.5 py-0.5 rounded ${
            positive
              ? 'bg-emerald-400/10 text-emerald-400'
              : 'bg-red-400/10 text-red-400'
          }`}
        >
          {positive ? '+' : ''}{delta}
        </span>
      )}
    </span>
  );
}
