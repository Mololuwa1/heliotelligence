import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer, ZAxis,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';
import EmptyState from '../shared/EmptyState.jsx';

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-lg px-3 py-2 text-xs">
      <p className="text-slate-400">{d.label}</p>
      <p className="text-amber-400 font-mono">Residual: {d.y?.toFixed(1)} kW</p>
      {d.flag_type && <p className="text-red-400 mt-1">{d.flag_type}</p>}
    </div>
  );
}

export default function AnomalyScatter({ anomalies, loading }) {
  if (loading) return <LoadingSpinner />;

  const items = anomalies?.flags ?? anomalies?.anomalies ?? anomalies?.items ?? [];
  if (!Array.isArray(items) || !items.length) {
    return <EmptyState title="No anomalies" message="No flagged intervals in this time window." />;
  }

  const data = items.map((d, i) => {
    const t = d.time ?? d.timestamp ?? d.date;
    return {
      x: i,
      y: d.residual_kw ?? d.residual ?? 0,
      label: t ? format(parseISO(t), 'MMM d HH:mm') : `#${i}`,
      flag_type: d.flag_type ?? d.type ?? '',
    };
  });

  const maxAbs = Math.max(...data.map(d => Math.abs(d.y)), 1);

  return (
    <ResponsiveContainer width="100%" height={240}>
      <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2D3F55" />
        <XAxis
          dataKey="x"
          type="number"
          tick={false}
          axisLine={{ stroke: '#2D3F55' }}
          tickLine={false}
          label={{ value: 'Time →', position: 'insideRight', fill: '#475569', fontSize: 10 }}
        />
        <YAxis
          dataKey="y"
          type="number"
          domain={[-maxAbs * 1.1, maxAbs * 1.1]}
          tickFormatter={v => `${v.toFixed(0)} kW`}
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={60}
        />
        <ZAxis range={[20, 20]} />
        <Tooltip content={<CustomTooltip />} />
        <ReferenceLine y={0} stroke="#2D3F55" />
        <Scatter
          data={data}
          fill="#f59e0b"
          fillOpacity={0.7}
        />
      </ScatterChart>
    </ResponsiveContainer>
  );
}
