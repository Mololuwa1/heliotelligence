import { useState, useEffect, useCallback } from 'react';
import TopBar from '../layout/TopBar.jsx';
import SiteMap from './SiteMap.jsx';
import GroupDetailPanel from './GroupDetailPanel.jsx';
import { StatusLegend } from './InverterMarker.jsx';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';
import EmptyState from '../shared/EmptyState.jsx';
import { getLayout } from '../../api/sites.js';

const SITE_NAMES = {
  '5ab83b40-553c-5ddd-976f-71f6cb5d490f': 'Bracon Ash',
};

export default function DigitalTwinPage({ siteId }) {
  const [layout, setLayout] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getLayout(siteId)
      .then(data => {
        setLayout(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message ?? 'Failed to load layout');
        setLoading(false);
      });
  }, [siteId, refreshKey]);

  useEffect(() => { load(); }, [load]);

  const siteName = SITE_NAMES[siteId] ?? siteId;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <TopBar title={`${siteName} — Digital Twin`} onRefresh={() => setRefreshKey(k => k + 1)} />

      <div className="flex-1 flex min-h-0">
        {/* Map + summary */}
        <div className="flex-1 flex flex-col min-w-0 p-6 gap-4">
          {/* Site summary strip */}
          {layout && (
            <div className="flex gap-4 flex-wrap">
              {[
                { label: 'Capacity', value: layout.capacity_kwp?.toLocaleString(), unit: 'kWp' },
                { label: 'Tilt', value: layout.tilt_deg, unit: '°' },
                { label: 'Azimuth', value: layout.azimuth_deg, unit: '° (PVsyst)' },
                { label: 'Groups', value: layout.inverter_groups?.length },
              ].map(item => (
                <div key={item.label} className="bg-[#1E2A3A] border border-[#2D3F55] rounded-lg px-4 py-2.5 flex items-center gap-2">
                  <span className="text-slate-400 text-xs">{item.label}</span>
                  <span className="font-mono text-white text-sm font-semibold">
                    {item.value ?? '—'}{item.unit && <span className="text-slate-400 font-normal ml-0.5">{item.unit}</span>}
                  </span>
                </div>
              ))}
              {/* Legend */}
              <div className="ml-auto bg-[#1E2A3A] border border-[#2D3F55] rounded-lg px-4 py-2.5">
                <StatusLegend />
              </div>
            </div>
          )}

          {/* Map area */}
          <div className="flex-1 min-h-[400px] relative">
            {loading ? (
              <div className="h-full flex items-center justify-center bg-[#1E2A3A] border border-[#2D3F55] rounded-xl">
                <LoadingSpinner label="Loading layout…" />
              </div>
            ) : error ? (
              <div className="h-full flex items-center justify-center bg-[#1E2A3A] border border-[#2D3F55] rounded-xl">
                <EmptyState title="Layout unavailable" message={error} />
              </div>
            ) : (
              <SiteMap
                layoutData={layout}
                onGroupClick={setSelectedGroup}
              />
            )}
          </div>

          {/* Group list table */}
          {layout?.inverter_groups?.length > 0 && (
            <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-xl overflow-hidden">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-[#2D3F55]">
                    {['Group', 'Inverters', 'Active', 'Faulted', 'Availability', 'Status'].map(h => (
                      <th key={h} className="px-4 py-2.5 text-xs font-medium text-slate-500 uppercase tracking-wider">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {layout.inverter_groups.map(g => (
                    <tr
                      key={g.id}
                      className={`border-b border-[#2D3F55] cursor-pointer transition-colors hover:bg-white/5 ${
                        selectedGroup?.id === g.id ? 'bg-amber-400/5' : ''
                      }`}
                      onClick={() => setSelectedGroup(g)}
                    >
                      <td className="px-4 py-2.5 text-white text-sm font-medium">{g.id}</td>
                      <td className="px-4 py-2.5 text-slate-400 font-mono text-sm">{g.inverter_count}</td>
                      <td className="px-4 py-2.5 text-emerald-400 font-mono text-sm">{g.active_inverters ?? '—'}</td>
                      <td className="px-4 py-2.5 font-mono text-sm">
                        <span className={g.fault_inverters > 0 ? 'text-red-400' : 'text-slate-400'}>
                          {g.fault_inverters ?? '—'}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-slate-400 font-mono text-sm">
                        {g.availability_pct != null ? `${g.availability_pct.toFixed(1)}%` : '—'}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`text-xs font-medium capitalize ${
                          g.status === 'normal' ? 'text-emerald-400'
                          : g.status === 'degraded' ? 'text-amber-400'
                          : g.status === 'offline' ? 'text-red-400'
                          : 'text-slate-500'
                        }`}>
                          {g.status ?? 'unknown'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Side panel */}
        <GroupDetailPanel
          group={selectedGroup}
          onClose={() => setSelectedGroup(null)}
        />
      </div>
    </div>
  );
}
