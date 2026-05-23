import { useState, useEffect, useCallback } from 'react';
import TopBar from '../layout/TopBar.jsx';
import AlertCard from './AlertCard.jsx';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';
import EmptyState from '../shared/EmptyState.jsx';
import { getAlerts } from '../../api/sites.js';

const BRACON_ASH_ID = '5ab83b40-553c-5ddd-976f-71f6cb5d490f';

export default function AlertCentre() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [unackOnly, setUnackOnly] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getAlerts(BRACON_ASH_ID, { unacknowledgedOnly: unackOnly, limit: 100 })
      .then(data => {
        setAlerts(Array.isArray(data) ? data : data?.alerts ?? []);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message ?? 'Failed to load alerts');
        setLoading(false);
      });
  }, [unackOnly, refreshKey]);

  useEffect(() => { load(); }, [load]);

  function handleAcknowledged(id) {
    setAlerts(prev =>
      prev.map(a => (a.id === id ? { ...a, acknowledged: true } : a))
    );
  }

  const unackCount = alerts.filter(a => !a.acknowledged).length;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <TopBar title="Alert Centre" onRefresh={() => setRefreshKey(k => k + 1)} />

      <div className="flex-1 overflow-auto p-6">
        {/* Controls */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <span className="text-slate-400 text-sm">
              {loading ? '…' : `${alerts.length} alert${alerts.length !== 1 ? 's' : ''}`}
            </span>
            {unackCount > 0 && !unackOnly && (
              <span className="bg-red-500/20 text-red-400 text-xs font-medium px-2 py-0.5 rounded-full">
                {unackCount} unacknowledged
              </span>
            )}
          </div>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <span className="text-slate-400 text-sm">Unacknowledged only</span>
            <div
              onClick={() => setUnackOnly(v => !v)}
              className={`relative inline-flex h-5 w-9 rounded-full transition-colors ${
                unackOnly ? 'bg-amber-400' : 'bg-[#2D3F55]'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform mt-0.5 ${
                  unackOnly ? 'translate-x-4.5' : 'translate-x-0.5'
                }`}
              />
            </div>
          </label>
        </div>

        {/* Alert list */}
        {loading ? (
          <LoadingSpinner label="Loading alerts…" />
        ) : error ? (
          <EmptyState title="Failed to load alerts" message={error} />
        ) : alerts.length === 0 ? (
          <EmptyState title="No alerts" message={unackOnly ? 'No unacknowledged alerts.' : 'No alerts in the system.'} />
        ) : (
          <div className="space-y-3 max-w-3xl">
            {alerts.map(alert => (
              <AlertCard
                key={alert.id}
                alert={alert}
                onAcknowledged={handleAcknowledged}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
