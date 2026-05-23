import { useState, useEffect, useCallback } from 'react';
import TopBar from '../layout/TopBar.jsx';
import KPIStrip from './KPIStrip.jsx';
import PRTrendChart from './PRTrendChart.jsx';
import LossWaterfall from './LossWaterfall.jsx';
import AnomalyScatter from './AnomalyScatter.jsx';
import InverterTimeline from './InverterTimeline.jsx';
import { useRouter } from '../../router.jsx';
import { useTimeRange } from '../../contexts/TimeRangeContext.jsx';
import {
  getLayout,
  getBenchmarking,
  getDegradation,
  getAnomalies,
  getInverterHealth,
} from '../../api/sites.js';

function Section({ title, children }) {
  return (
    <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-[#2D3F55]">
        <h2 className="text-white font-semibold text-sm">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

export default function SitePage({ siteId }) {
  const { navigate } = useRouter();
  const { start, end } = useTimeRange();

  const [siteName, setSiteName] = useState(null);
  const [benchmarking, setBenchmarking] = useState(null);
  const [degradation, setDegradation] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [inverterHealth, setInverterHealth] = useState(null);

  const [loadingBench, setLoadingBench] = useState(true);
  const [loadingDeg, setLoadingDeg] = useState(true);
  const [loadingAnom, setLoadingAnom] = useState(true);
  const [loadingInv, setLoadingInv] = useState(true);

  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    getLayout(siteId).then(d => setSiteName(d?.site_name ?? null)).catch(() => {});
  }, [siteId]);

  const load = useCallback(() => {
    setLoadingBench(true);
    setLoadingDeg(true);
    setLoadingAnom(true);
    setLoadingInv(true);

    getBenchmarking(siteId, start, end)
      .then(setBenchmarking)
      .catch(() => setBenchmarking(null))
      .finally(() => setLoadingBench(false));

    getDegradation(siteId, start, end)
      .then(setDegradation)
      .catch(() => setDegradation(null))
      .finally(() => setLoadingDeg(false));

    getAnomalies(siteId, start, end)
      .then(setAnomalies)
      .catch(() => setAnomalies(null))
      .finally(() => setLoadingAnom(false));

    getInverterHealth(siteId, start, end)
      .then(setInverterHealth)
      .catch(() => setInverterHealth(null))
      .finally(() => setLoadingInv(false));
  }, [siteId, start, end, refreshKey]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <TopBar title={siteName ?? '—'} onRefresh={() => setRefreshKey(k => k + 1)} />

      <div className="flex-1 overflow-auto p-6 space-y-6">
        {/* Twin link */}
        <div className="flex justify-end">
          <button
            onClick={() => navigate(`/site/${siteId}/twin`)}
            className="text-xs text-amber-400 hover:text-amber-300 border border-amber-400/30 rounded-lg px-3 py-1.5 transition-colors"
          >
            View Digital Twin →
          </button>
        </div>

        {/* KPI Strip */}
        <KPIStrip benchmarking={benchmarking} degradation={degradation} />

        {/* Charts grid */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <Section title="Daily Performance Ratio">
            <PRTrendChart degradation={degradation} loading={loadingDeg} />
          </Section>

          <Section title="Loss Waterfall">
            <LossWaterfall benchmarking={benchmarking} loading={loadingBench} />
          </Section>

          <Section title="Anomaly Scatter — Power Residuals">
            <AnomalyScatter anomalies={anomalies} loading={loadingAnom} />
          </Section>

          <Section title="Inverter Group Health">
            <InverterTimeline inverterHealth={inverterHealth} loading={loadingInv} />
          </Section>
        </div>
      </div>
    </div>
  );
}
