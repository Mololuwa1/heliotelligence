import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Cell, ResponsiveContainer, LabelList,
} from 'recharts';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';
import EmptyState from '../shared/EmptyState.jsx';

const BUCKETS = [
  { key: 'optical_pct',      label: 'Optical',      fill: '#ef4444' },
  { key: 'temperature_pct',  label: 'Temperature',  fill: '#f59e0b' },
  { key: 'dc_losses_pct',    label: 'DC Losses',    fill: '#ef4444' },
  { key: 'inverter_pct',     label: 'Inverter',     fill: '#ef4444' },
  { key: 'clipping_pct',     label: 'Clipping',     fill: '#f59e0b' },
  { key: 'availability_pct', label: 'Availability', fill: '#ef4444' },
  { key: 'unaccounted_pct',  label: 'Unaccounted',  fill: '#7f1d1d' },
];

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-lg px-3 py-2 text-xs">
      <p className="text-white font-medium">{d.label}</p>
      <p className="font-mono text-amber-400">{d.value != null ? `${d.value.toFixed(3)}%` : '—'}</p>
    </div>
  );
}

export default function LossWaterfall({ benchmarking, loading }) {
  if (loading) return <LoadingSpinner />;

  const losses = benchmarking?.losses ?? benchmarking ?? {};
  const hasData = BUCKETS.some(b => losses[b.key] != null);
  if (!hasData) return <EmptyState title="No loss data" message="Loss decomposition not available for this period." />;

  const data = BUCKETS.map(b => ({
    label: b.label,
    key: b.key,
    value: losses[b.key] ?? null,
    fill: b.fill,
  })).filter(d => d.value != null);

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 60, left: 90, bottom: 4 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#2D3F55" horizontal={false} />
        <XAxis
          type="number"
          tickFormatter={v => `${v}%`}
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="label"
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={85}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
        <Bar dataKey="value" radius={[0, 4, 4, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.fill} />
          ))}
          <LabelList
            dataKey="value"
            position="right"
            formatter={v => v != null ? `${v.toFixed(2)}%` : ''}
            style={{ fill: '#94a3b8', fontSize: 11 }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
