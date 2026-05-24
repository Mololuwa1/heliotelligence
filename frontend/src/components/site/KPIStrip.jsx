import PRChip from '../shared/PRChip.jsx';

function KPICard({ label, children }) {
  return (
    <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-xl px-5 py-4 flex-1 min-w-0">
      <p className="text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">{label}</p>
      <div className="font-mono text-2xl font-bold text-white">{children}</div>
    </div>
  );
}

export default function KPIStrip({ benchmarking, degradation, targetPr = null }) {
  const b = benchmarking ?? {};
  const pr = b.performance_ratio?.pr ?? null;
  const eActual = b.yield_metrics?.e_actual_kwh ?? null;
  const availability = b.availability?.availability_pct ?? null;
  const unaccounted = b.losses?.unaccounted_pct ?? b.unaccounted_pct ?? null;
  const degRate = degradation?.rate_pct_per_year ?? null;

  return (
    <div className="flex gap-4 overflow-x-auto pb-1">
      <KPICard label="Performance Ratio">
        <PRChip value={pr} showDelta targetPr={targetPr} />
      </KPICard>

      <KPICard label="Energy">
        <span className="text-white">
          {eActual != null ? (eActual / 1000).toFixed(1) : '—'}
        </span>
        <span className="text-slate-400 text-base font-normal ml-1">MWh</span>
      </KPICard>

      <KPICard label="Availability">
        <span className={availability != null && availability < 90 ? 'text-red-400' : 'text-white'}>
          {availability != null ? `${availability.toFixed(1)}%` : '—'}
        </span>
      </KPICard>

      <KPICard label="Degradation">
        <span className={degRate != null && degRate < -1 ? 'text-amber-400' : 'text-white'}>
          {degRate != null ? `${degRate.toFixed(2)}%/yr` : '—'}
        </span>
      </KPICard>

      <KPICard label="Unaccounted Loss">
        <span className={unaccounted != null && unaccounted > 5 ? 'text-red-400' : 'text-white'}>
          {unaccounted != null ? `${unaccounted.toFixed(1)}%` : '—'}
        </span>
      </KPICard>
    </div>
  );
}
