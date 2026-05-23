import {
  ComposedChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';
import EmptyState from '../shared/EmptyState.jsx';

const GROUP_ORDER = ['MQA11', 'MQA21', 'MQA22', 'MQA23'];

function eventColour(type) {
  if (!type) return '#94a3b8';
  const t = type.toLowerCase();
  if (t.includes('offline') || t.includes('fault')) return '#ef4444';
  if (t.includes('comms') || t.includes('communication')) return '#f59e0b';
  if (t.includes('degraded') || t.includes('underperform')) return '#f59e0b';
  return '#94a3b8';
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-lg px-3 py-2 text-xs space-y-1">
      <p className="text-white font-medium">{d.group}</p>
      <p className="text-slate-400">{d.label}</p>
      <p className="font-mono text-amber-400">
        Fault events: {d.faultCount ?? 0}
      </p>
      {d.availability != null && (
        <p className={`font-mono ${d.availability < 90 ? 'text-red-400' : 'text-emerald-400'}`}>
          Avail: {d.availability.toFixed(1)}%
        </p>
      )}
    </div>
  );
}

export default function InverterTimeline({ inverterHealth, loading }) {
  if (loading) return <LoadingSpinner />;

  // Support both the per-inverter list (inverters) and the flat fault_events list
  const inverters = inverterHealth?.inverters ?? [];
  const flatEvents = inverterHealth?.fault_events ?? [];
  const hasData = inverters.length > 0 || flatEvents.length > 0;
  if (!hasData) {
    return <EmptyState title="No inverter health data" message="No inverter health records in this window." />;
  }

  // Aggregate by group — works from either source
  const groupMap = {};
  if (inverters.length > 0) {
    for (const inv of inverters) {
      const group = inv.group_id ?? (inv.inverter_id ?? '').rsplit?.('-TB', 1)?.[0] ?? inv.inverter_id;
      if (!groupMap[group]) groupMap[group] = { faultCount: 0, availSum: 0, count: 0 };
      groupMap[group].faultCount += inv.fault_event_count ?? (inv.fault_events ?? []).length;
      if (inv.availability_pct != null) {
        groupMap[group].availSum += inv.availability_pct;
        groupMap[group].count += 1;
      }
    }
  } else {
    // Build from flat fault_events: group_id = everything before last -TB
    for (const ev of flatEvents) {
      const invId = ev.inverter_id ?? '';
      const group = invId.includes('-TB') ? invId.split('-TB')[0] : invId;
      if (!groupMap[group]) groupMap[group] = { faultCount: 0, availSum: 0, count: 0 };
      groupMap[group].faultCount += 1;
    }
  }

  const data = GROUP_ORDER
    .filter(g => groupMap[g])
    .map(g => {
      const entry = groupMap[g];
      const availability = entry.count > 0 ? entry.availSum / entry.count : null;
      const status =
        availability == null ? 'unknown'
        : availability >= 95 ? 'normal'
        : availability >= 50 ? 'degraded'
        : 'offline';
      return {
        group: g,
        label: `Group ${g}`,
        faultCount: entry.faultCount,
        availability,
        status,
        barValue: entry.faultCount > 0 ? entry.faultCount : 0.5,
      };
    });

  if (!data.length) {
    return <EmptyState title="No group data" message="Could not aggregate by inverter group." />;
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <ComposedChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 40, left: 60, bottom: 4 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#2D3F55" horizontal={false} />
        <XAxis
          type="number"
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          label={{ value: 'Fault Events', position: 'insideBottom', offset: -4, fill: '#475569', fontSize: 10 }}
        />
        <YAxis
          type="category"
          dataKey="group"
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={55}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
        <Bar dataKey="barValue" radius={[0, 4, 4, 0]}>
          {data.map((d, i) => (
            <Cell
              key={i}
              fill={
                d.status === 'offline' ? '#ef4444'
                : d.status === 'degraded' ? '#f59e0b'
                : d.faultCount > 0 ? '#f59e0b'
                : '#10b981'
              }
            />
          ))}
        </Bar>
      </ComposedChart>
    </ResponsiveContainer>
  );
}
