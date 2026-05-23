import { useRouter } from '../../router.jsx';

const STATUS_COLOURS = {
  normal:   '#10b981',
  degraded: '#f6ad55',
  offline:  '#ef4444',
  unknown:  '#94a3b8',
};

const STATUS_BG = {
  normal:   'rgba(16,185,129,0.15)',
  degraded: 'rgba(246,173,85,0.15)',
  offline:  'rgba(239,68,68,0.15)',
  unknown:  'rgba(148,163,184,0.15)',
};

function statusColour(s) { return STATUS_COLOURS[s] ?? STATUS_COLOURS.unknown; }
function statusBg(s)     { return STATUS_BG[s] ?? STATUS_BG.unknown; }

export default function GroupDetailPanel({ group, onClose, siteId }) {
  const { navigate } = useRouter();

  if (!group) return null;

  const inverters = group.inverters ?? [];

  return (
    <div
      className="absolute top-4 right-4 bottom-4 w-72 flex flex-col rounded-xl overflow-hidden z-10"
      style={{ background: 'rgba(11,17,32,0.95)', border: '1px solid #1E2A3A', backdropFilter: 'blur(12px)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#1E2A3A]">
        <div className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{ background: statusColour(group.status) }}
          />
          <span className="text-white font-bold font-mono text-sm">{group.id}</span>
          <span
            className="text-xs px-2 py-0.5 rounded-full capitalize font-medium"
            style={{ color: statusColour(group.status), background: statusBg(group.status) }}
          >
            {group.status}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-500 hover:text-white transition-colors text-lg leading-none"
          aria-label="Close"
        >
          ×
        </button>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-2 p-3 border-b border-[#1E2A3A]">
        {[
          { label: 'Total Inverters', value: group.inverter_count },
          { label: 'Active',          value: group.active_inverters,  colour: '#10b981' },
          { label: 'Faulted',         value: group.fault_inverters,   colour: group.fault_inverters > 0 ? '#ef4444' : '#94a3b8' },
          { label: 'Availability',    value: group.availability_pct != null ? `${group.availability_pct.toFixed(1)}%` : '—' },
        ].map(stat => (
          <div key={stat.label} className="bg-[#0F1629] border border-[#1E2A3A] rounded-lg p-3">
            <p className="text-slate-500 text-xs mb-1">{stat.label}</p>
            <p
              className="font-mono font-bold text-lg"
              style={{ color: stat.colour ?? '#ffffff' }}
            >
              {stat.value ?? '—'}
            </p>
          </div>
        ))}
      </div>

      {/* Inverter list */}
      <div className="flex-1 overflow-y-auto p-3">
        <p className="text-amber-400 text-xs font-medium uppercase tracking-wider mb-2">
          Inverters ({inverters.length})
        </p>
        {inverters.length === 0 ? (
          <p className="text-slate-500 text-xs">No inverter IDs configured.</p>
        ) : (
          <div className="space-y-1">
            {inverters.map(invId => {
              // Active if group is active and we infer proportionally
              const isActive = group.active_inverters > 0;
              return (
                <div
                  key={invId}
                  className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[#0F1629] border border-[#1E2A3A]"
                >
                  <span
                    className="w-2 h-2 rounded-full flex-shrink-0"
                    style={{ background: isActive ? '#10b981' : '#ef4444' }}
                  />
                  <span className="text-slate-300 font-mono text-xs truncate">{invId}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-[#1E2A3A]">
        <button
          onClick={() => siteId && navigate(`/site/${siteId}`)}
          className="w-full text-center text-xs text-amber-400 hover:text-amber-300 border border-amber-400/30 hover:border-amber-400/60 rounded-lg py-2 transition-colors"
        >
          View Analytics →
        </button>
      </div>
    </div>
  );
}
