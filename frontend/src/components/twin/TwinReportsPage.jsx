import { useState, useEffect } from 'react';
import { formatISO } from 'date-fns';
import TwinNavBar from './TwinNavBar.jsx';
import { generateReport, getLayout } from '../../api/sites.js';
import { useTimeRange } from '../../contexts/TimeRangeContext.jsx';

const SECTIONS = [
  'Executive Summary',
  'Performance Ratio Analysis',
  'Energy Yield & Capacity Factor',
  'Degradation & Loss Breakdown',
  'Inverter Health & Fault Events',
  'Anomaly Detection Results',
  'Alerts & Incident Log',
  'Benchmarking vs Reference',
];

function LabelledInput({ label, ...props }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-slate-400 text-xs">{label}</label>
      <input
        {...props}
        className="bg-[#0F1629] border border-[#1E2A3A] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-400/50"
      />
    </div>
  );
}

export default function TwinReportsPage({ siteId }) {
  const { start: ctxStart, end: ctxEnd } = useTimeRange();

  const [startVal, setStartVal] = useState(formatISO(ctxStart, { representation: 'date' }));
  const [endVal, setEndVal]     = useState(formatISO(ctxEnd,   { representation: 'date' }));
  const [sections, setSections] = useState(() => Object.fromEntries(SECTIONS.map(s => [s, true])));
  const [status, setStatus]     = useState('idle'); // idle | loading | success | error
  const [layout, setLayout]     = useState(null);

  useEffect(() => {
    getLayout(siteId).then(setLayout).catch(() => {});
  }, [siteId]);

  function toggleSection(s) {
    setSections(prev => ({ ...prev, [s]: !prev[s] }));
  }

  async function handleGenerate() {
    setStatus('loading');
    try {
      const response = await generateReport(siteId, new Date(startVal), new Date(endVal));
      const url = URL.createObjectURL(response.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = `heliotelligence-report-${startVal}-${endVal}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      setStatus('success');
      setTimeout(() => setStatus('idle'), 4000);
    } catch {
      setStatus('error');
      setTimeout(() => setStatus('idle'), 4000);
    }
  }

  const allChecked = Object.values(sections).every(Boolean);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0B1120] overflow-hidden">
      <TwinNavBar activePage="Reports" siteId={siteId} />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="flex gap-6 h-full">
          {/* Left: configuration */}
          <div
            className="flex flex-col gap-5 flex-shrink-0 overflow-y-auto"
            style={{ width: 400 }}
          >
            <div className="bg-[#0F1629] border border-[#1E2A3A] rounded-xl p-5">
              <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-4">Date Range</p>
              <div className="flex flex-col gap-3">
                <LabelledInput
                  label="Start Date"
                  type="date"
                  value={startVal}
                  onChange={e => setStartVal(e.target.value)}
                />
                <LabelledInput
                  label="End Date"
                  type="date"
                  value={endVal}
                  onChange={e => setEndVal(e.target.value)}
                />
              </div>
            </div>

            <div className="bg-[#0F1629] border border-[#1E2A3A] rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <p className="text-amber-400 text-xs font-bold uppercase tracking-widest">Report Sections</p>
                <button
                  onClick={() => setSections(Object.fromEntries(SECTIONS.map(s => [s, !allChecked])))}
                  className="text-xs text-slate-400 hover:text-amber-400 transition-colors"
                >
                  {allChecked ? 'Deselect All' : 'Select All'}
                </button>
              </div>
              <div className="flex flex-col gap-2">
                {SECTIONS.map(s => (
                  <label key={s} className="flex items-center gap-3 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={sections[s]}
                      onChange={() => toggleSection(s)}
                      className="w-4 h-4 rounded border-[#2D3F55] bg-[#0B1120] text-amber-400 focus:ring-amber-400/30 accent-amber-400"
                    />
                    <span className="text-sm text-slate-300 group-hover:text-white transition-colors">{s}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Generate button */}
            <button
              onClick={handleGenerate}
              disabled={status === 'loading'}
              className={`w-full py-3 rounded-xl font-semibold text-sm transition-all ${
                status === 'loading'
                  ? 'bg-amber-400/20 text-amber-400 cursor-not-allowed'
                  : status === 'success'
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                  : status === 'error'
                  ? 'bg-red-500/20 text-red-400 border border-red-500/40'
                  : 'bg-amber-400 text-[#0B1120] hover:bg-amber-300'
              }`}
            >
              {status === 'loading' ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  Generating report…
                </span>
              ) : status === 'success' ? (
                'Report ready — downloading…'
              ) : status === 'error' ? (
                'Generation failed — retry'
              ) : (
                'Generate Report'
              )}
            </button>
          </div>

          {/* Right: preview */}
          <div className="flex-1 bg-[#0F1629] border border-[#1E2A3A] rounded-xl p-8 flex flex-col">
            {/* Branding header */}
            <div className="flex items-start justify-between mb-8 pb-6 border-b border-[#1E2A3A]">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-6 h-6 rounded bg-amber-400/20 flex items-center justify-center">
                    <svg className="w-3.5 h-3.5 text-amber-400" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M12 2.25a.75.75 0 01.75.75v2.25a.75.75 0 01-1.5 0V3a.75.75 0 01.75-.75zM7.5 12a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0z" />
                    </svg>
                  </div>
                  <span className="text-white font-bold text-sm tracking-wide">HELIOTELLIGENCE</span>
                </div>
                <p className="text-slate-400 text-xs">Solar Farm Performance Report</p>
              </div>
              <div className="text-right">
                <p className="text-slate-500 text-xs">Generated</p>
                <p className="text-white font-mono text-xs">{new Date().toISOString().slice(0, 10)}</p>
              </div>
            </div>

            {/* Metadata */}
            <div className="grid grid-cols-2 gap-x-8 gap-y-4 mb-8">
              {[
                { label: 'Site',        value: layout?.site_name ?? '—' },
                { label: 'Site ID',     value: siteId.slice(0, 8) + '…' },
                { label: 'Report From', value: startVal },
                { label: 'Report To',   value: endVal },
                { label: 'Capacity',    value: layout?.capacity_kwp != null ? `${(layout.capacity_kwp / 1000).toFixed(1)} MWp` : '—' },
                { label: 'Location',    value: layout?.centre_lat != null && layout?.centre_lon != null ? `${layout.centre_lat.toFixed(4)}°N, ${layout.centre_lon.toFixed(4)}°E` : '—' },
              ].map(({ label, value }) => (
                <div key={label} className="flex flex-col gap-1">
                  <span className="text-slate-500 text-xs">{label}</span>
                  <span className="text-white text-sm font-mono">{value}</span>
                </div>
              ))}
            </div>

            {/* Sections list */}
            <div>
              <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-3">Included Sections</p>
              <div className="space-y-1.5">
                {SECTIONS.filter(s => sections[s]).map((s, i) => (
                  <div key={s} className="flex items-center gap-3 text-sm text-slate-300">
                    <span className="text-slate-600 font-mono text-xs w-5">{String(i + 1).padStart(2, '0')}</span>
                    {s}
                  </div>
                ))}
                {!Object.values(sections).some(Boolean) && (
                  <p className="text-slate-500 text-xs italic">No sections selected.</p>
                )}
              </div>
            </div>

            <div className="mt-auto pt-6 border-t border-[#1E2A3A]">
              <p className="text-slate-600 text-xs">
                Heliotelligence Platform · Confidential · Generated automatically
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
