import { useState, useEffect, useCallback, useMemo } from 'react';
import TwinNavBar from './TwinNavBar.jsx';
import AlertCard from '../alerts/AlertCard.jsx';
import { getLayout, getAlerts } from '../../api/sites.js';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';

const SEVERITIES = ['critical', 'warning', 'info'];

function SummaryPill({ label, count, colour }) {
  return (
    <div
      className="flex flex-col items-center px-6 py-3 rounded-xl border"
      style={{ background: `${colour}10`, borderColor: `${colour}30` }}
    >
      <span className="font-mono font-bold text-2xl" style={{ color: colour }}>{count}</span>
      <span className="text-slate-400 text-xs mt-0.5 capitalize">{label}</span>
    </div>
  );
}

export default function TwinAlertsPage({ siteId }) {
  const [siteName, setSiteName] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [severityFilter, setSeverityFilter] = useState('All');
  const [statusFilter, setStatusFilter]   = useState('All');
  const [search, setSearch] = useState('');

  useEffect(() => {
    getLayout(siteId).then(d => setSiteName(d?.site_name ?? null)).catch(() => {});
  }, [siteId]);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getAlerts(siteId, { limit: 200 })
      .then(data => {
        setAlerts(Array.isArray(data) ? data : data?.alerts ?? []);
        setLoading(false);
      })
      .catch(() => { setError('Failed to load alerts.'); setLoading(false); });
  }, [siteId]);

  useEffect(() => { load(); }, [load]);

  function handleAcknowledged(id) {
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, acknowledged: true } : a));
  }

  const counts = useMemo(() => {
    const c = { critical: 0, warning: 0, info: 0 };
    for (const a of alerts) {
      const sev = (a.severity ?? 'info').toLowerCase();
      if (sev in c) c[sev]++;
    }
    return c;
  }, [alerts]);

  const filtered = useMemo(() => {
    return alerts.filter(a => {
      const sev = (a.severity ?? 'info').toLowerCase();
      if (severityFilter !== 'All' && sev !== severityFilter.toLowerCase()) return false;
      if (statusFilter === 'Active' && a.acknowledged) return false;
      if (statusFilter === 'Acknowledged' && !a.acknowledged) return false;
      if (search && !(a.message ?? '').toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [alerts, severityFilter, statusFilter, search]);

  const allHealthy = !loading && !error && alerts.length === 0;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0B1120] overflow-hidden">
      <TwinNavBar activePage="Alerts" siteId={siteId} siteName={siteName} />

      <div className="flex-1 overflow-y-auto">
        {/* Summary strip */}
        <div className="flex items-center gap-4 px-6 py-4 border-b border-[#1E2A3A] bg-[#080F1E]">
          <SummaryPill label="Critical" count={counts.critical} colour="#ef4444" />
          <SummaryPill label="Warning"  count={counts.warning}  colour="#f59e0b" />
          <SummaryPill label="Info"     count={counts.info}     colour="#94a3b8" />

          {/* Filter bar */}
          <div className="flex items-center gap-3 ml-6">
            <select
              value={severityFilter}
              onChange={e => setSeverityFilter(e.target.value)}
              className="bg-[#0F1629] border border-[#1E2A3A] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-amber-400/50"
            >
              <option value="All">All Severities</option>
              {SEVERITIES.map(s => <option key={s} value={s} className="capitalize">{s}</option>)}
            </select>
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="bg-[#0F1629] border border-[#1E2A3A] rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-amber-400/50"
            >
              <option value="All">All Statuses</option>
              <option value="Active">Active</option>
              <option value="Acknowledged">Acknowledged</option>
            </select>
            <input
              type="text"
              placeholder="Search messages…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="bg-[#0F1629] border border-[#1E2A3A] rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-amber-400/50 w-48"
            />
          </div>

          {!loading && (
            <span className="text-slate-500 text-xs ml-auto">
              {filtered.length} / {alerts.length} alerts
            </span>
          )}
        </div>

        {/* Alert feed */}
        <div className="px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <LoadingSpinner label="Loading alerts…" />
            </div>
          ) : error ? (
            <p className="text-center text-red-400 text-sm py-16">{error}</p>
          ) : allHealthy ? (
            <div className="flex flex-col items-center justify-center py-24 gap-4">
              <div className="w-16 h-16 rounded-full bg-emerald-500/15 flex items-center justify-center">
                <svg className="w-8 h-8 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <p className="text-white font-semibold">All systems healthy</p>
              <p className="text-slate-400 text-sm">No alerts have been raised for this site.</p>
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-center text-slate-500 text-sm py-16">No alerts match the current filters.</p>
          ) : (
            <div className="space-y-3 max-w-3xl">
              {filtered.map(alert => (
                <AlertCard key={alert.id} alert={alert} onAcknowledged={handleAcknowledged} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
