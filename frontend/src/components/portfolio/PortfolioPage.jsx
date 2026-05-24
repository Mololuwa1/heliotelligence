import { useState, useEffect, useCallback } from 'react';
import TopBar from '../layout/TopBar.jsx';
import FleetKPICard from './FleetKPICard.jsx';
import SiteRow from './SiteRow.jsx';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';
import { getBenchmarking, getLayout } from '../../api/sites.js';
import { useTimeRange } from '../../contexts/TimeRangeContext.jsx';

const SITES = [
  {
    id: '5ab83b40-553c-5ddd-976f-71f6cb5d490f',
    name: 'Bracon Ash',
    capacity_kwp: 28524,
  },
];

export default function PortfolioPage() {
  const { start, end } = useTimeRange();
  const [benchmarkingMap, setBenchmarkingMap] = useState({});
  const [layoutMap, setLayoutMap] = useState({});
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    const [benchResults, layoutResults] = await Promise.all([
      Promise.allSettled(SITES.map(site => getBenchmarking(site.id, start, end))),
      Promise.allSettled(SITES.map(site => getLayout(site.id))),
    ]);
    const bMap = {};
    benchResults.forEach((r, i) => {
      if (r.status === 'fulfilled') bMap[SITES[i].id] = r.value;
    });
    const lMap = {};
    layoutResults.forEach((r, i) => {
      if (r.status === 'fulfilled') lMap[SITES[i].id] = r.value;
    });
    setBenchmarkingMap(bMap);
    setLayoutMap(lMap);
    setLoading(false);
  }, [start, end, refreshKey]);

  useEffect(() => { load(); }, [load]);

  // Aggregate fleet KPIs
  const allBench = Object.values(benchmarkingMap);
  const totalCapacity = SITES.reduce((s, site) => s + site.capacity_kwp, 0);
  const avgPR =
    allBench.length > 0
      ? allBench.reduce((s, b) => s + (b.performance_ratio?.pr ?? 0), 0) / allBench.length
      : null;
  const totalEnergy = allBench.reduce((s, b) => s + (b.yield_metrics?.e_actual_kwh ?? 0), 0);
  const avgAvail =
    allBench.length > 0
      ? allBench.reduce((s, b) => s + (b.availability?.availability_pct ?? 0), 0) / allBench.length
      : null;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <TopBar title="Portfolio" onRefresh={() => setRefreshKey(k => k + 1)} />

      <div className="flex-1 overflow-auto p-6 space-y-6">
        {/* Fleet KPIs */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <FleetKPICard
            label="Total Capacity"
            value={totalCapacity.toLocaleString()}
            unit="kWp"
          />
          <FleetKPICard
            label="Fleet PR"
            value={avgPR != null ? (avgPR * 100).toFixed(1) : '—'}
            unit="%"
            accent
          />
          <FleetKPICard
            label="Energy Generated"
            value={totalEnergy > 0 ? (totalEnergy / 1000).toFixed(1) : '—'}
            unit="MWh"
            sub={`Last ${30} days`}
          />
          <FleetKPICard
            label="Avg Availability"
            value={avgAvail != null ? avgAvail.toFixed(1) : '—'}
            unit="%"
          />
        </div>

        {/* Sites table */}
        <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[#2D3F55]">
            <h2 className="text-white font-semibold text-sm">Sites</h2>
          </div>

          {loading ? (
            <LoadingSpinner label="Loading site data…" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-[#2D3F55]">
                    {['Site', 'Capacity', 'PR', 'Availability', 'Energy', ''].map(h => (
                      <th key={h} className="px-5 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {SITES.map(site => (
                    <SiteRow
                      key={site.id}
                      site={site}
                      benchmarking={benchmarkingMap[site.id]}
                      targetPr={layoutMap[site.id]?.pvsyst_pr_target_pct ?? null}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
