export default function FleetKPICard({ label, value, unit, sub, accent = false }) {
  return (
    <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-xl p-5">
      <p className="text-slate-400 text-xs font-medium uppercase tracking-wider mb-3">{label}</p>
      <div className="flex items-end gap-1.5">
        <span
          className={`font-mono text-2xl font-bold ${accent ? 'text-amber-400' : 'text-white'}`}
        >
          {value ?? '—'}
        </span>
        {unit && <span className="text-slate-400 text-sm mb-0.5">{unit}</span>}
      </div>
      {sub && <p className="text-slate-500 text-xs mt-1.5">{sub}</p>}
    </div>
  );
}
