import { useState, useEffect, useMemo } from 'react';
import TwinNavBar from './TwinNavBar.jsx';
import { getLayout, getInverterHealth } from '../../api/sites.js';
import { useTimeRange } from '../../contexts/TimeRangeContext.jsx';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';

function invStatus(availPct) {
  if (availPct == null) return 'unknown';
  if (availPct >= 95) return 'normal';
  if (availPct >= 50) return 'degraded';
  return 'offline';
}

function StatusBadge({ status }) {
  const cfg = {
    normal:   'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    degraded: 'bg-amber-400/15 text-amber-400 border-amber-400/30',
    offline:  'bg-red-500/15 text-red-400 border-red-500/30',
    unknown:  'bg-slate-700/50 text-slate-400 border-slate-600',
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-xs font-medium capitalize ${cfg[status] ?? cfg.unknown}`}>
      {status}
    </span>
  );
}

function downtimeHours(faultEvents) {
  if (!Array.isArray(faultEvents) || !faultEvents.length) return 0;
  let total = 0;
  for (const ev of faultEvents) {
    if (ev.duration_hours != null) {
      total += ev.duration_hours;
    } else if (ev.start_time && ev.end_time) {
      const diff = (new Date(ev.end_time) - new Date(ev.start_time)) / 3600000;
      if (!isNaN(diff)) total += diff;
    }
  }
  return total;
}

function DetailPanel({ inv, onClose }) {
  const faultEvents = inv.fault_events ?? [];
  return (
    <div
      className="fixed inset-y-0 right-0 w-96 flex flex-col z-[60] border-l border-[#1E2A3A]"
      style={{ background: '#080F1E', top: 56 }}
    >
      <div className="flex items-center justify-between px-5 py-4 border-b border-[#1E2A3A]">
        <div>
          <p className="text-white font-mono font-bold">{inv.inverter_id}</p>
          <p className="text-slate-400 text-xs mt-0.5">Group {inv.group_id ?? '—'}</p>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
      </div>

      <div className="px-5 py-4 border-b border-[#1E2A3A] grid grid-cols-2 gap-3">
        {[
          { label: 'Status',       value: <StatusBadge status={invStatus(inv.availability_pct)} /> },
          { label: 'Availability', value: inv.availability_pct != null ? `${inv.availability_pct.toFixed(1)}%` : '—' },
          { label: 'Fault Events', value: faultEvents.length },
          { label: 'Downtime',     value: `${downtimeHours(faultEvents).toFixed(1)} h` },
        ].map(({ label, value }) => (
          <div key={label} className="flex flex-col gap-1">
            <span className="text-slate-500 text-xs">{label}</span>
            <span className="text-white text-sm font-mono font-semibold">{value}</span>
          </div>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-3">
          Fault Event History ({faultEvents.length})
        </p>
        {faultEvents.length === 0 ? (
          <p className="text-slate-500 text-xs">No fault events in this period.</p>
        ) : (
          <div className="space-y-2">
            {faultEvents.map((ev, i) => (
              <div key={i} className="rounded-lg p-3 border border-[#1E2A3A] bg-[#0F1629]">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-red-400 uppercase tracking-wide">
                    {ev.event_type ?? ev.type ?? 'Fault'}
                  </span>
                  {ev.duration_hours != null && (
                    <span className="text-xs font-mono text-slate-400">{ev.duration_hours.toFixed(2)} h</span>
                  )}
                </div>
                {ev.start_time && (
                  <p className="text-slate-400 text-xs font-mono">
                    {new Date(ev.start_time).toISOString().slice(0, 16).replace('T', ' ')}
                    {ev.end_time ? ` → ${new Date(ev.end_time).toISOString().slice(11, 16)}` : ''}
                  </p>
                )}
                {ev.message && <p className="text-slate-300 text-xs mt-1">{ev.message}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function TwinAssetsPage({ siteId }) {
  const { start, end } = useTimeRange();
  const [siteName, setSiteName] = useState(null);
  const [groupIds, setGroupIds] = useState([]);
  const [inverterHealth, setInverterHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [groupFilter, setGroupFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [selectedInv, setSelectedInv] = useState(null);

  useEffect(() => {
    getLayout(siteId)
      .then(d => {
        setSiteName(d?.site_name ?? null);
        setGroupIds((d?.inverter_groups ?? []).map(g => g.id));
      })
      .catch(() => {});
  }, [siteId]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getInverterHealth(siteId, start, end)
      .then(data => { setInverterHealth(data); setLoading(false); })
      .catch(() => { setError('Failed to load inverter health data.'); setLoading(false); });
  }, [siteId, start, end]);

  const inverters = useMemo(() => {
    const raw = inverterHealth?.inverters ?? inverterHealth?.results ?? [];
    return raw.map(inv => ({
      ...inv,
      _faultCount: (inv.fault_events ?? []).length,
      _downtime: downtimeHours(inv.fault_events ?? []),
      _status: invStatus(inv.availability_pct),
    }));
  }, [inverterHealth]);

  const filtered = useMemo(() => {
    return inverters
      .filter(inv => {
        const id = (inv.inverter_id ?? '').toLowerCase();
        if (search && !id.includes(search.toLowerCase())) return false;
        if (groupFilter !== 'All' && inv.group_id !== groupFilter) return false;
        if (statusFilter !== 'All' && inv._status !== statusFilter.toLowerCase()) return false;
        return true;
      })
      .sort((a, b) => b._faultCount - a._faultCount);
  }, [inverters, search, groupFilter, statusFilter]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0B1120] overflow-hidden">
      <TwinNavBar activePage="Assets" siteId={siteId} siteName={siteName} />

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Filter bar */}
          <div className="flex items-center gap-3 px-6 py-3 border-b border-[#1E2A3A] bg-[#080F1E] flex-shrink-0">
            <input
              type="text"
              placeholder="Search inverter ID…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="bg-[#0F1629] border border-[#1E2A3A] rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-amber-400/50 w-48"
            />
            <select
              value={groupFilter}
              onChange={e => setGroupFilter(e.target.value)}
              className="bg-[#0F1629] border border-[#1E2A3A] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-amber-400/50"
            >
              <option value="All">All Groups</option>
              {groupIds.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="bg-[#0F1629] border border-[#1E2A3A] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-amber-400/50"
            >
              <option value="All">All Statuses</option>
              <option value="Normal">Normal</option>
              <option value="Degraded">Degraded</option>
              <option value="Offline">Offline</option>
            </select>
            {!loading && (
              <span className="text-slate-500 text-xs ml-auto">
                {filtered.length} / {inverters.length} inverters
              </span>
            )}
          </div>

          {/* Table */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center h-full">
                <LoadingSpinner label="Loading inverter health…" />
              </div>
            ) : error ? (
              <div className="flex items-center justify-center h-full">
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-[#080F1E] border-b border-[#1E2A3A]">
                  <tr>
                    {['Inverter ID', 'Group', 'Status', 'Fault Events', 'Total Downtime (h)', 'Availability %'].map(col => (
                      <th key={col} className="px-4 py-3 text-left text-slate-400 font-medium uppercase tracking-wide text-xs">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-12 text-center text-slate-500">
                        No inverters match the current filters.
                      </td>
                    </tr>
                  ) : (
                    filtered.map((inv, i) => (
                      <tr
                        key={inv.inverter_id ?? i}
                        onClick={() => setSelectedInv(inv)}
                        className={`border-b border-[#1E2A3A] cursor-pointer transition-colors ${
                          selectedInv?.inverter_id === inv.inverter_id
                            ? 'bg-amber-400/5'
                            : 'hover:bg-white/3'
                        }`}
                      >
                        <td className="px-4 py-3 font-mono text-white font-medium">{inv.inverter_id ?? '—'}</td>
                        <td className="px-4 py-3 text-slate-300">{inv.group_id ?? '—'}</td>
                        <td className="px-4 py-3"><StatusBadge status={inv._status} /></td>
                        <td className="px-4 py-3 font-mono text-center">
                          <span className={inv._faultCount > 0 ? 'text-red-400 font-semibold' : 'text-slate-400'}>
                            {inv._faultCount}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-slate-300">{inv._downtime.toFixed(1)}</td>
                        <td className="px-4 py-3 font-mono">
                          <span className={
                            inv.availability_pct == null ? 'text-slate-500'
                            : inv.availability_pct >= 95 ? 'text-emerald-400'
                            : inv.availability_pct >= 50 ? 'text-amber-400'
                            : 'text-red-400'
                          }>
                            {inv.availability_pct != null ? `${inv.availability_pct.toFixed(1)}%` : '—'}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Slide-in detail panel */}
        {selectedInv && (
          <DetailPanel inv={selectedInv} onClose={() => setSelectedInv(null)} />
        )}
      </div>
    </div>
  );
}
