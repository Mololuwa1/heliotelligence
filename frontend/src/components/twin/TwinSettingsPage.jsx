import { useState, useEffect } from 'react';
import TwinNavBar from './TwinNavBar.jsx';
import { getLayout, getGeometry } from '../../api/sites.js';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';

const STATUS_STYLE = {
  normal:   'text-emerald-400',
  degraded: 'text-amber-400',
  offline:  'text-red-400',
  unknown:  'text-slate-500',
};

function Section({ title, children }) {
  return (
    <div className="bg-[#0F1629] border border-[#1E2A3A] rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-[#1E2A3A]">
        <h2 className="text-amber-400 text-xs font-bold uppercase tracking-widest">{title}</h2>
      </div>
      <div className="px-5 py-2">{children}</div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[#1E2A3A] last:border-0">
      <span className="text-slate-400 text-xs">{label}</span>
      <span className="font-mono text-xs text-white">{value ?? '—'}</span>
    </div>
  );
}

export default function TwinSettingsPage({ siteId }) {
  const [layout, setLayout]     = useState(null);
  const [geometry, setGeometry] = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getLayout(siteId).catch(() => null),
      getGeometry(siteId, 1).catch(() => null),
    ]).then(([lay, geo]) => {
      setLayout(lay);
      setGeometry(geo);
      setLoading(false);
    }).catch(() => {
      setError('Failed to load site configuration.');
      setLoading(false);
    });
  }, [siteId]);

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-[#0B1120] overflow-hidden">
        <TwinNavBar activePage="Settings" siteId={siteId} />
        <div className="flex-1 flex items-center justify-center">
          <LoadingSpinner label="Loading site configuration…" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-[#0B1120] overflow-hidden">
        <TwinNavBar activePage="Settings" siteId={siteId} />
        <div className="flex-1 flex items-center justify-center">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  const groups = layout?.inverter_groups ?? [];

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0B1120] overflow-hidden">
      <TwinNavBar activePage="Settings" siteId={siteId} />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto grid grid-cols-2 gap-5">

          {/* Site Identity */}
          <Section title="Site Identity">
            <Row label="Name"       value={layout?.site_name} />
            <Row label="Site ID"    value={siteId} />
            <Row label="Latitude"   value={layout?.centre_lat != null ? `${layout.centre_lat.toFixed(5)} °N` : null} />
            <Row label="Longitude"  value={layout?.centre_lon != null ? `${layout.centre_lon.toFixed(5)} °E` : null} />
            <Row label="DC Capacity" value={layout?.capacity_kwp != null ? `${(layout.capacity_kwp / 1000).toFixed(2)} MWp` : null} />
            <Row label="Tilt"        value={layout?.tilt_deg != null ? `${layout.tilt_deg}°` : null} />
            <Row label="Azimuth"     value={layout?.azimuth_deg != null ? `${layout.azimuth_deg}° (PVsyst)` : null} />
          </Section>

          {/* Array Configuration */}
          <Section title="Array Configuration">
            <Row label="Tilt"         value={geometry?.tilt_deg != null ? `${geometry.tilt_deg}°` : null} />
            <Row label="Azimuth"      value={geometry?.azimuth_deg != null ? `${geometry.azimuth_deg}° (PVsyst)` : null} />
            <Row label="Row Pitch"    value={geometry?.row_pitch_m != null ? `${geometry.row_pitch_m} m` : null} />
            <Row label="Table Width"  value={geometry?.table_width_m != null ? `${geometry.table_width_m} m` : null} />
            <Row label="Total Panels" value={geometry?.total_panels != null ? geometry.total_panels.toLocaleString() : null} />
            <Row label="Module Width" value={geometry?.module_width_m != null ? `${geometry.module_width_m} m` : null} />
            <Row label="Module Height" value={geometry?.module_height_m != null ? `${geometry.module_height_m} m` : null} />
          </Section>

          {/* Inverter Groups */}
          <Section title="Inverter Groups">
            {groups.length === 0 ? (
              <p className="text-slate-500 text-xs py-2">No group data available.</p>
            ) : (
              groups.map(g => (
                <div key={g.id} className="py-2.5 border-b border-[#1E2A3A] last:border-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-white font-mono font-medium text-xs">{g.id}</span>
                    <span className="text-slate-400 text-xs">{g.inverter_count} inverters</span>
                  </div>
                  <div className="flex gap-4 text-xs font-mono">
                    <span className="text-slate-500">Lat: {g.centre_lat?.toFixed(5)}</span>
                    <span className="text-slate-500">Lon: {g.centre_lon?.toFixed(5)}</span>
                    {g.availability_pct != null && (
                      <span className="text-slate-400">Avail: {g.availability_pct.toFixed(1)}%</span>
                    )}
                    {g.status && (
                      <span className={STATUS_STYLE[g.status] ?? STATUS_STYLE.unknown}>
                        {g.status}
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </Section>

        </div>
      </div>
    </div>
  );
}
