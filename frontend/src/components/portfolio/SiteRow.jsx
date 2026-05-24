import { useRouter } from '../../router.jsx';
import StatusDot from '../shared/StatusDot.jsx';
import PRChip from '../shared/PRChip.jsx';

export default function SiteRow({ site, benchmarking, targetPr = null }) {
  const { navigate } = useRouter();

  const availability = benchmarking?.availability?.availability_pct ?? null;
  const pr = benchmarking?.performance_ratio?.pr ?? null;
  const eActual = benchmarking?.yield_metrics?.e_actual_kwh ?? null;

  const status =
    availability == null ? 'unknown'
    : availability >= 95 ? 'normal'
    : availability >= 50 ? 'degraded'
    : 'offline';

  return (
    <tr
      className="border-b border-[#2D3F55] hover:bg-white/5 cursor-pointer transition-colors"
      onClick={() => navigate(`/site/${site.id}`)}
    >
      <td className="px-5 py-4">
        <div className="flex items-center gap-3">
          <StatusDot status={status} />
          <span className="text-white font-medium text-sm">{site.name}</span>
        </div>
      </td>
      <td className="px-5 py-4 text-slate-400 font-mono text-sm">
        {site.capacity_kwp?.toLocaleString()} kWp
      </td>
      <td className="px-5 py-4">
        <PRChip value={pr} showDelta targetPr={targetPr} />
      </td>
      <td className="px-5 py-4 text-slate-400 font-mono text-sm">
        {availability != null ? `${availability.toFixed(1)}%` : '—'}
      </td>
      <td className="px-5 py-4 text-slate-400 font-mono text-sm">
        {eActual != null ? `${(eActual / 1000).toFixed(1)} MWh` : '—'}
      </td>
      <td className="px-5 py-4">
        <button
          onClick={e => { e.stopPropagation(); navigate(`/site/${site.id}/twin`); }}
          className="text-xs text-slate-400 hover:text-amber-400 transition-colors"
        >
          Twin →
        </button>
      </td>
    </tr>
  );
}
