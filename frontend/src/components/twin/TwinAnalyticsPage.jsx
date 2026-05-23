import { useState, useEffect, useCallback } from 'react';
import TwinNavBar from './TwinNavBar.jsx';
import PRTrendChart from '../site/PRTrendChart.jsx';
import LossWaterfall from '../site/LossWaterfall.jsx';
import AnomalyScatter from '../site/AnomalyScatter.jsx';
import InverterTimeline from '../site/InverterTimeline.jsx';
import { getBenchmarking, getDegradation, getAnomalies, getInverterHealth } from '../../api/sites.js';
import { useTimeRange } from '../../contexts/TimeRangeContext.jsx';

function ChartPanel({ title, children }) {
  return (
    <div className="flex flex-col bg-[#0F1629] border border-[#1E2A3A] rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-[#1E2A3A] flex-shrink-0">
        <h2 className="text-white font-semibold text-sm">{title}</h2>
      </div>
      <div className="flex-1 p-5 min-h-0 flex flex-col justify-center">
        {children}
      </div>
    </div>
  );
}

export default function TwinAnalyticsPage({ siteId }) {
  const { start, end } = useTimeRange();
  const [benchmarking, setBenchmarking] = useState(null);
  const [degradation, setDegradation] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [inverterHealth, setInverterHealth] = useState(null);

  const [loadingBench, setLoadingBench] = useState(true);
  const [loadingDeg,   setLoadingDeg]   = useState(true);
  const [loadingAnom,  setLoadingAnom]  = useState(true);
  const [loadingInv,   setLoadingInv]   = useState(true);

  const load = useCallback(() => {
    setLoadingBench(true);
    setLoadingDeg(true);
    setLoadingAnom(true);
    setLoadingInv(true);

    getBenchmarking(siteId, start, end)
      .then(setBenchmarking).catch(() => setBenchmarking(null))
      .finally(() => setLoadingBench(false));

    getDegradation(siteId, start, end)
      .then(setDegradation).catch(() => setDegradation(null))
      .finally(() => setLoadingDeg(false));

    getAnomalies(siteId, start, end)
      .then(setAnomalies).catch(() => setAnomalies(null))
      .finally(() => setLoadingAnom(false));

    getInverterHealth(siteId, start, end)
      .then(setInverterHealth).catch(() => setInverterHealth(null))
      .finally(() => setLoadingInv(false));
  }, [siteId, start, end]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0B1120] overflow-hidden">
      <TwinNavBar activePage="Analytics" siteId={siteId} />

      <div className="flex-1 overflow-y-auto p-5">
        <div className="grid grid-cols-2 grid-rows-2 gap-5 h-full min-h-[600px]">
          <ChartPanel title="PR Trend — Daily vs Target 86.56%">
            <PRTrendChart degradation={degradation} loading={loadingDeg} />
          </ChartPanel>

          <ChartPanel title="Loss Waterfall">
            <LossWaterfall benchmarking={benchmarking} loading={loadingBench} />
          </ChartPanel>

          <ChartPanel title="Anomaly Scatter — Residuals vs Time">
            <AnomalyScatter anomalies={anomalies} loading={loadingAnom} />
          </ChartPanel>

          <ChartPanel title="Inverter Availability — Fault Events by Group">
            <InverterTimeline inverterHealth={inverterHealth} loading={loadingInv} />
          </ChartPanel>
        </div>
      </div>
    </div>
  );
}
