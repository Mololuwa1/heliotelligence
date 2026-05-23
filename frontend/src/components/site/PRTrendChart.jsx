import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';
import EmptyState from '../shared/EmptyState.jsx';

function CustomTooltip({ active, payload, label, targetPr }) {
  if (!active || !payload?.length) return null;
  const pr = payload.find(p => p.dataKey === 'pr_pct');
  const delta = pr && targetPr != null ? (pr.value - targetPr).toFixed(2) : null;
  return (
    <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-lg px-3 py-2 text-xs">
      <p className="text-slate-400 mb-1">{label}</p>
      {pr && (
        <p className="text-amber-400 font-mono font-semibold">
          PR: {pr.value.toFixed(2)}%
          {delta != null && (
            <span className={`ml-2 ${parseFloat(delta) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              ({parseFloat(delta) >= 0 ? '+' : ''}{delta})
            </span>
          )}
        </p>
      )}
    </div>
  );
}

export default function PRTrendChart({ degradation, loading, targetPr = null }) {
  if (loading) return <LoadingSpinner />;

  const raw = degradation?.daily_pr ?? [];
  if (!raw.length) return <EmptyState title="No PR data" message="No daily PR records in this window." />;

  const data = raw.map(d => ({
    date: format(parseISO(d.date ?? d.time ?? d.day), 'MMM d'),
    pr_pct: d.pr != null ? parseFloat((d.pr * 100).toFixed(2)) : d.pr_pct ?? null,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2D3F55" />
        <XAxis
          dataKey="date"
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={{ stroke: '#2D3F55' }}
          tickLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          domain={[60, 100]}
          tickFormatter={v => `${v}%`}
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={42}
        />
        <Tooltip content={<CustomTooltip targetPr={targetPr} />} />
        {targetPr != null && (
          <ReferenceLine
            y={targetPr}
            stroke="rgba(255,255,255,0.35)"
            strokeDasharray="6 4"
            label={{ value: `Target ${targetPr}%`, position: 'right', fill: '#94a3b8', fontSize: 10 }}
          />
        )}
        <Line
          type="monotone"
          dataKey="pr_pct"
          name="Daily PR"
          stroke="#f59e0b"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, fill: '#f59e0b' }}
          connectNulls={false}
        />
        <Legend
          wrapperStyle={{ fontSize: 12, color: '#94a3b8' }}
          formatter={() => 'Daily PR'}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
