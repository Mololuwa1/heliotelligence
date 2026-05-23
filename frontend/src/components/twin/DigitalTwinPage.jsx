import { useState, useEffect, useCallback } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip as RechartsTip,
  PieChart, Pie, Cell,
} from 'recharts';
import { useRouter } from '../../router.jsx';
import { useTimeRange } from '../../contexts/TimeRangeContext.jsx';
import SiteMap from './SiteMap.jsx';
import GroupDetailPanel from './GroupDetailPanel.jsx';
import { getLayout, getBenchmarking, getAlerts } from '../../api/sites.js';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';

// ─── Design constants ──────────────────────────────────────────────────────────
const STATUS_COLOURS = {
  normal:   '#10b981',
  degraded: '#f6ad55',
  offline:  '#ef4444',
  unknown:  '#94a3b8',
};
function statusColour(s) { return STATUS_COLOURS[s] ?? STATUS_COLOURS.unknown; }

const BRACON_ASH_ID = '5ab83b40-553c-5ddd-976f-71f6cb5d490f';

// ─── Synthetic day-profile data for AreaChart ──────────────────────────────────
const DAY_PROFILE = Array.from({ length: 17 }, (_, i) => {
  const hour = i + 5;           // 05:00 → 21:00 UTC
  const peak = 22.8;            // MW at solar noon
  const x = (hour - 13) / 4.5; // normalised distance from noon
  const mw = Math.max(0, peak * Math.exp(-x * x));
  return { time: `${String(hour).padStart(2, '0')}:00`, mw: parseFloat(mw.toFixed(2)) };
});

// ─── TwinNavBar ───────────────────────────────────────────────────────────────
const NAV_TABS = ['Overview', 'Assets', 'Analytics', 'Alerts', 'Reports', 'Settings'];

function TwinNavBar({ activeTab, onTab, siteId }) {
  const { navigate } = useRouter();
  const [utc, setUtc] = useState('');

  useEffect(() => {
    function tick() {
      setUtc(new Date().toUTCString().slice(17, 25) + ' UTC');
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center px-5 py-0 bg-[#060D1A] border-b border-[#1E2A3A] flex-shrink-0" style={{ height: 56 }}>
      {/* Left: branding */}
      <div className="flex flex-col justify-center mr-8 min-w-max">
        <span className="text-white font-bold text-xs tracking-widest uppercase leading-none">Solar Farm Digital Twin</span>
        <span className="text-amber-400 text-xs leading-none mt-0.5">Bracon Ash</span>
      </div>

      {/* Centre: tabs */}
      <nav className="flex gap-1 flex-1">
        {NAV_TABS.map(tab => (
          <button
            key={tab}
            onClick={() => onTab(tab)}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors font-medium ${
              activeTab === tab
                ? 'text-amber-400 bg-amber-400/10'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            {tab}
          </button>
        ))}
      </nav>

      {/* Right: weather + clock + back */}
      <div className="flex items-center gap-4 ml-4 flex-shrink-0">
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <svg className="h-4 w-4 text-amber-400" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2.25a.75.75 0 01.75.75v2.25a.75.75 0 01-1.5 0V3a.75.75 0 01.75-.75zM7.5 12a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM18.894 6.166a.75.75 0 00-1.06-1.06l-1.591 1.59a.75.75 0 101.06 1.061l1.591-1.59zM21.75 12a.75.75 0 01-.75.75h-2.25a.75.75 0 010-1.5H21a.75.75 0 01.75.75zM17.834 18.894a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 10-1.061 1.06l1.59 1.591zM12 18a.75.75 0 01.75.75V21a.75.75 0 01-1.5 0v-2.25A.75.75 0 0112 18zM7.758 17.303a.75.75 0 00-1.061-1.06l-1.591 1.59a.75.75 0 001.06 1.061l1.591-1.59zM6 12a.75.75 0 01-.75.75H3a.75.75 0 010-1.5h2.25A.75.75 0 016 12zM6.697 7.757a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 00-1.061 1.06l1.59 1.591z" />
          </svg>
          <span>Clear Sky 14°C</span>
        </div>
        <span className="font-mono text-xs text-slate-500">{utc}</span>
        <button
          onClick={() => navigate(`/site/${siteId}`)}
          className="text-xs text-slate-500 hover:text-white border border-[#1E2A3A] rounded px-2 py-1 transition-colors"
        >
          ← Analytics
        </button>
      </div>
    </div>
  );
}

// ─── LeftPanel ────────────────────────────────────────────────────────────────
function MetricRow({ label, value, colour }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-[#1E2A3A] last:border-0">
      <span className="text-slate-400 text-xs">{label}</span>
      <span className="font-mono text-xs font-semibold" style={{ color: colour ?? '#ffffff' }}>
        {value ?? '—'}
      </span>
    </div>
  );
}

function LeftPanel({ benchmarking, layout }) {
  const prVal  = benchmarking?.performance_ratio?.pr;
  const eActual = benchmarking?.yield_metrics?.e_actual_kwh;
  const cfVal  = benchmarking?.yield_metrics?.capacity_factor_pct;
  const hours  = benchmarking?.yield_metrics?.hours_in_window ?? 1;

  const pr         = prVal   != null ? (prVal * 100).toFixed(2) + '%' : '—';
  const cf         = cfVal   != null ? cfVal.toFixed(1) + '%'         : '—';
  const eActualGwh = eActual != null ? (eActual / 1e6).toFixed(3) + ' GWh' : '—';
  const currentMw  = eActual != null ? (eActual / hours / 1000).toFixed(2) + ' MW' : '—';

  const overallStatus = layout?.inverter_groups?.every(g => g.status === 'normal')
    ? 'normal' : 'degraded';

  return (
    <div
      className="flex flex-col overflow-y-auto flex-shrink-0 border-r border-[#1E2A3A]"
      style={{ width: 260, background: '#080F1E' }}
    >
      {/* Plant Overview */}
      <div className="p-4 border-b border-[#1E2A3A]">
        <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-3">Plant Overview</p>
        <MetricRow label="Total Capacity" value="28.5 MWp" />
        <MetricRow label="DC Capacity" value="28.5 MWdc" />
        <MetricRow label="AC Capacity" value="21.1 MWac" />
        <MetricRow label="Annual Generation" value={eActualGwh} />
        <MetricRow label="Performance Ratio" value={pr} colour="#f59e0b" />
        <MetricRow label="Capacity Factor" value={cf} />
        <div className="flex items-center justify-between pt-1.5">
          <span className="text-slate-400 text-xs">Status</span>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ background: statusColour(overallStatus) }} />
            <span className="font-mono text-xs font-semibold capitalize" style={{ color: statusColour(overallStatus) }}>
              {overallStatus}
            </span>
          </div>
        </div>
      </div>

      {/* Real-time Metrics */}
      <div className="p-4 border-b border-[#1E2A3A]">
        <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-3">Real-time Metrics</p>
        <MetricRow label="⚡ Current Power" value={currentMw} colour="#f59e0b" />
        <MetricRow label="☀ Irradiance" value="— W/m²" />
        <MetricRow label="🌡 Module Temp" value="— °C" />
        <MetricRow label="🌡 Ambient Temp" value="— °C" />
        <MetricRow label="💨 Wind Speed" value="— m/s" />
        <MetricRow label="💧 Humidity" value="— %" />
      </div>

      {/* Power Output chart */}
      <div className="p-4 border-b border-[#1E2A3A]">
        <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-3">Power Output (Synthetic)</p>
        <ResponsiveContainer width="100%" height={140}>
          <AreaChart data={DAY_PROFILE} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
            <defs>
              <linearGradient id="amberGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#f59e0b" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="time"
              tick={{ fill: '#475569', fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              interval={3}
            />
            <YAxis
              tick={{ fill: '#475569', fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              domain={[0, 25]}
              tickFormatter={v => `${v}`}
            />
            <RechartsTip
              contentStyle={{ background: '#0F1629', border: '1px solid #1E2A3A', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#94a3b8' }}
              itemStyle={{ color: '#f59e0b' }}
              formatter={v => [`${v} MW`, 'Power']}
            />
            <Area
              type="monotone"
              dataKey="mw"
              stroke="#f59e0b"
              strokeWidth={2}
              fill="url(#amberGrad)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ─── MapOverlay ───────────────────────────────────────────────────────────────
function MapOverlay({ groups }) {
  if (!groups?.length) return null;
  return (
    <div className="absolute bottom-4 left-4 flex gap-2 z-10 flex-wrap">
      {groups.map(g => (
        <div
          key={g.id}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs"
          style={{ background: 'rgba(11,17,32,0.85)', border: '1px solid #1E2A3A' }}
        >
          <div
            className="w-2 h-2 rounded-full"
            style={{ background: statusColour(g.status) }}
          />
          <span className="text-white font-mono">{g.id}</span>
          <span className="text-slate-400">{g.active_inverters}/{g.inverter_count}</span>
        </div>
      ))}
    </div>
  );
}

// ─── RightPanel ───────────────────────────────────────────────────────────────
const SEVERITY_COLOURS = {
  critical: '#ef4444',
  warning:  '#f59e0b',
  info:     '#94a3b8',
};

const PIE_COLOURS = ['#10b981', '#f59e0b', '#ef4444'];

function RightPanel({ benchmarking, layout, alerts, siteId }) {
  const { navigate } = useRouter();

  // Donut data from layout groups
  const groups = layout?.inverter_groups ?? [];
  const normalCount  = groups.filter(g => g.status === 'normal').length;
  const degradedCount = groups.filter(g => g.status === 'degraded').length;
  const offlineCount = groups.filter(g => g.status === 'offline' || g.status === 'unknown').length;
  const pieData = [
    { name: 'Normal',   value: normalCount  || 0 },
    { name: 'Warning',  value: degradedCount || 0 },
    { name: 'Fault',    value: offlineCount  || 0 },
  ].filter(d => d.value > 0);

  // Environmental impact
  const eKwh = benchmarking?.yield_metrics?.e_actual_kwh ?? 0;
  const co2T = (eKwh * 0.233 / 1000).toFixed(0);
  const treesEquiv = Math.round(parseFloat(co2T) * 45).toLocaleString();
  const coalT = (eKwh * 0.000341).toFixed(0);

  const recentAlerts = (Array.isArray(alerts) ? alerts : []).slice(0, 5);

  return (
    <div
      className="flex flex-col overflow-y-auto flex-shrink-0 border-l border-[#1E2A3A]"
      style={{ width: 260, background: '#080F1E' }}
    >
      {/* Asset Status donut */}
      <div className="p-4 border-b border-[#1E2A3A]">
        <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-2">Asset Status</p>
        <div className="relative">
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie
                data={pieData.length ? pieData : [{ name: 'No data', value: 1 }]}
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={75}
                paddingAngle={3}
                dataKey="value"
                strokeWidth={0}
              >
                {(pieData.length ? pieData : [{ name: 'No data', value: 1 }]).map((_, i) => (
                  <Cell key={i} fill={PIE_COLOURS[i] ?? '#94a3b8'} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="text-white font-mono font-bold text-xl">66</span>
            <span className="text-slate-500 text-xs">Total Assets</span>
          </div>
        </div>
        <div className="flex justify-around">
          {[
            { label: 'Normal',  count: normalCount,   colour: '#10b981' },
            { label: 'Warning', count: degradedCount, colour: '#f59e0b' },
            { label: 'Fault',   count: offlineCount,  colour: '#ef4444' },
          ].map(s => (
            <div key={s.label} className="flex flex-col items-center gap-0.5">
              <span className="font-mono font-bold text-sm" style={{ color: s.colour }}>{s.count}</span>
              <span className="text-slate-500 text-xs">{s.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Asset Breakdown */}
      <div className="p-4 border-b border-[#1E2A3A]">
        <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-3">Asset Breakdown</p>
        {[
          { icon: '📦', label: 'PV Modules',        value: '49,824' },
          { icon: '⚡', label: 'Inverters',          value: '66' },
          { icon: '🔌', label: 'Strings',            value: '2,076' },
          { icon: '🌤', label: 'Weather Stations',   value: '1' },
        ].map(row => (
          <div key={row.label} className="flex items-center justify-between py-1.5 border-b border-[#1E2A3A] last:border-0">
            <span className="text-slate-400 text-xs">{row.icon} {row.label}</span>
            <span className="font-mono text-xs text-white font-semibold">{row.value}</span>
          </div>
        ))}
      </div>

      {/* Alerts */}
      <div className="p-4 border-b border-[#1E2A3A]">
        <div className="flex items-center justify-between mb-3">
          <p className="text-amber-400 text-xs font-bold uppercase tracking-widest">Alerts</p>
          <button
            onClick={() => navigate('/alerts')}
            className="text-xs text-slate-400 hover:text-amber-400 transition-colors"
          >
            View All →
          </button>
        </div>
        {recentAlerts.length === 0 ? (
          <p className="text-slate-500 text-xs">No recent alerts.</p>
        ) : (
          <div className="space-y-2">
            {recentAlerts.map(alert => {
              const sev = (alert.severity ?? 'info').toLowerCase();
              const colour = SEVERITY_COLOURS[sev] ?? SEVERITY_COLOURS.info;
              return (
                <div
                  key={alert.id}
                  className="rounded-lg p-2.5"
                  style={{ background: `${colour}12`, border: `1px solid ${colour}30` }}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: colour }} />
                    <span className="text-xs font-medium uppercase tracking-wide" style={{ color: colour }}>{sev}</span>
                  </div>
                  <p className="text-slate-300 text-xs leading-relaxed line-clamp-2">{alert.message}</p>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Environmental Impact */}
      <div className="p-4">
        <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-3">Environmental Impact</p>
        {[
          { label: 'CO₂ Avoided', value: `${co2T} t` },
          { label: 'Trees Equiv', value: treesEquiv },
          { label: 'Coal Saved',  value: `${coalT} t` },
        ].map(row => (
          <div key={row.label} className="flex items-center justify-between py-1.5 border-b border-[#1E2A3A] last:border-0">
            <span className="text-slate-400 text-xs">{row.label}</span>
            <span className="font-mono text-xs text-emerald-400 font-semibold">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── DigitalTwinPage ──────────────────────────────────────────────────────────
export default function DigitalTwinPage({ siteId }) {
  const { start, end } = useTimeRange();

  const [layout, setLayout] = useState(null);
  const [benchmarking, setBenchmarking] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [activeTab, setActiveTab] = useState('Overview');
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);

    getLayout(siteId)
      .then(setLayout)
      .catch(() => setLayout(null))
      .finally(() => setLoading(false));

    getBenchmarking(siteId, start, end)
      .then(setBenchmarking)
      .catch(() => setBenchmarking(null));

    getAlerts(siteId, { limit: 5 })
      .then(data => setAlerts(Array.isArray(data) ? data : data?.alerts ?? []))
      .catch(() => setAlerts([]));
  }, [siteId, start, end, refreshKey]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0B1120] overflow-hidden">
      <TwinNavBar
        activeTab={activeTab}
        onTab={setActiveTab}
        siteId={siteId}
      />

      <div className="flex flex-1 overflow-hidden">
        <LeftPanel benchmarking={benchmarking} layout={layout} />

        {/* Map area */}
        <div className="flex-1 relative overflow-hidden">
          {loading ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <LoadingSpinner label="Loading digital twin…" />
            </div>
          ) : (
            <>
              <SiteMap
                layoutData={layout}
                onGroupClick={setSelectedGroup}
              />
              <MapOverlay groups={layout?.inverter_groups} />
              {selectedGroup && (
                <GroupDetailPanel
                  group={selectedGroup}
                  onClose={() => setSelectedGroup(null)}
                  siteId={siteId}
                />
              )}
            </>
          )}
        </div>

        <RightPanel
          benchmarking={benchmarking}
          layout={layout}
          alerts={alerts}
          siteId={siteId}
        />
      </div>
    </div>
  );
}
