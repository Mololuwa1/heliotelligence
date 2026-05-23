import StatusDot from '../shared/StatusDot.jsx';
import { statusToRgb } from './InverterMarker.jsx';

export default function GroupDetailPanel({ group, onClose }) {
  if (!group) {
    return (
      <div className="bg-[#0F1629] border-l border-[#2D3F55] w-72 flex flex-col p-6">
        <p className="text-slate-500 text-sm text-center mt-16">
          Click an inverter group on the map to see details.
        </p>
      </div>
    );
  }

  const rgb = statusToRgb(group.status);
  const pulseColor = `rgba(${rgb.join(',')}, 0.3)`;

  return (
    <div className="bg-[#0F1629] border-l border-[#2D3F55] w-72 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-[#2D3F55]">
        <div className="flex items-center gap-2">
          <StatusDot status={group.status} />
          <h3 className="text-white font-semibold text-sm">{group.id}</h3>
        </div>
        <button
          onClick={onClose}
          className="text-slate-500 hover:text-white transition-colors"
          aria-label="Close panel"
        >
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto p-5 space-y-5">
        <p className="text-slate-400 text-xs">{group.label}</p>

        {/* Status badge */}
        <div
          className="rounded-lg px-4 py-3"
          style={{ backgroundColor: pulseColor, border: `1px solid rgba(${rgb.join(',')}, 0.4)` }}
        >
          <p className="text-xs font-medium uppercase tracking-wider mb-1"
             style={{ color: `rgb(${rgb.join(',')})` }}>
            {group.status}
          </p>
          {group.availability_pct != null && (
            <p className="font-mono text-2xl font-bold text-white">
              {group.availability_pct.toFixed(1)}
              <span className="text-sm font-normal text-slate-400 ml-1">% avail.</span>
            </p>
          )}
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: 'Total Inverters', value: group.inverter_count },
            { label: 'Active', value: group.active_inverters, colour: 'text-emerald-400' },
            { label: 'Faulted', value: group.fault_inverters, colour: group.fault_inverters > 0 ? 'text-red-400' : 'text-white' },
            { label: 'Availability', value: group.availability_pct != null ? `${group.availability_pct.toFixed(1)}%` : '—' },
          ].map(stat => (
            <div key={stat.label} className="bg-[#1E2A3A] border border-[#2D3F55] rounded-lg p-3">
              <p className="text-slate-500 text-xs mb-1">{stat.label}</p>
              <p className={`font-mono font-bold text-lg ${stat.colour ?? 'text-white'}`}>
                {stat.value ?? '—'}
              </p>
            </div>
          ))}
        </div>

        {/* Coordinates */}
        <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-lg p-3">
          <p className="text-slate-500 text-xs mb-2">Centre Coordinates</p>
          <p className="font-mono text-xs text-slate-300">
            {group.centre_lat?.toFixed(6)}°N
          </p>
          <p className="font-mono text-xs text-slate-300">
            {group.centre_lon?.toFixed(6)}°E
          </p>
        </div>
      </div>
    </div>
  );
}
