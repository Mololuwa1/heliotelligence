import { useState, useEffect } from 'react';
import TwinNavBar from './TwinNavBar.jsx';
import { getLayout, getGeometry } from '../../api/sites.js';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';

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

  // Derive values from API responses + known Bracon Ash constants
  const groups = layout?.inverter_groups ?? [];
  const totalInverters = groups.reduce((s, g) => s + (g.inverter_count ?? 0), 0);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0B1120] overflow-hidden">
      <TwinNavBar activePage="Settings" siteId={siteId} />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto grid grid-cols-2 gap-5">

          {/* Site Identity */}
          <Section title="Site Identity">
            <Row label="Name"       value={layout?.site_name ?? 'Bracon Ash Solar Farm'} />
            <Row label="Site ID"    value={siteId} />
            <Row label="Latitude"   value="52.5626 °N" />
            <Row label="Longitude"  value="1.2132 °E" />
            <Row label="Timezone"   value="Europe/London" />
            <Row label="Altitude"   value="~40 m" />
            <Row label="Country"    value="United Kingdom" />
            <Row label="Region"     value="Norfolk, East England" />
          </Section>

          {/* Array Configuration */}
          <Section title="Array Configuration">
            <Row label="DC Capacity"    value="28.5 MWp" />
            <Row label="AC Capacity"    value="21.1 MWac" />
            <Row
              label="Tilt"
              value={geometry?.tilt_deg != null ? `${geometry.tilt_deg}°` : '15°'}
            />
            <Row
              label="Azimuth (PVsyst)"
              value={geometry?.azimuth_deg != null ? `${geometry.azimuth_deg}°` : '-0.6°'}
            />
            <Row
              label="Row Pitch"
              value={geometry?.row_pitch_m != null ? `${geometry.row_pitch_m} m` : '~0.65 m / GCR'}
            />
            <Row
              label="Row Length"
              value={geometry?.row_length_m != null ? `${geometry.row_length_m} m` : '54.67 m'}
            />
            <Row label="GCR"           value="~0.35" />
            <Row label="Hub Height"    value="~0.8 m" />
          </Section>

          {/* Module Configuration */}
          <Section title="Module Configuration">
            <Row label="Model"              value="JKM570N-72HL4-BDV" />
            <Row label="Technology"         value="TOPCon" />
            <Row label="Bifacial"           value="Yes" />
            <Row label="Nameplate Power"    value="570 Wp" />
            <Row
              label="Total Modules"
              value={geometry?.total_panels != null ? geometry.total_panels.toLocaleString() : '49,824'}
            />
            <Row label="Module Width"       value={geometry?.module_width_m != null ? `${geometry.module_width_m} m` : '2.278 m'} />
            <Row label="Module Height"      value={geometry?.module_height_m != null ? `${geometry.module_height_m} m` : '1.134 m'} />
            <Row label="Modules per String" value="24" />
          </Section>

          {/* Inverter Configuration */}
          <Section title="Inverter Configuration">
            <Row label="Model"           value="SMA Sunny Central 630CP-JP" />
            <Row label="Total Count"     value={totalInverters || 66} />
            <Row label="Nominal Power"   value="630 kVA" />
            <Row label="Max Efficiency"  value="98.6 %" />
            <Row label="Grid Voltage"    value="33 kV" />
            <Row label="Grid Limit"      value="21.1 MWac" />
            {groups.map(g => (
              <Row key={g.id} label={`Group ${g.id}`} value={`${g.inverter_count} inverters`} />
            ))}
          </Section>

          {/* Loss Parameters */}
          <Section title="Loss Parameters">
            <Row label="Soiling Loss"      value="2.0 %" />
            <Row label="LID Loss"          value="1.5 %" />
            <Row label="Mismatch Loss"     value="1.0 %" />
            <Row label="DC Wiring Loss"    value="1.5 %" />
            <Row label="AC Wiring Loss"    value="0.5 %" />
            <Row label="Unavailability"    value="1.0 %" />
            <Row label="Other Losses"      value="0.5 %" />
            <Row label="Total Loss Est."   value="~7.5 %" />
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
                  <div className="flex gap-4 text-xs text-slate-500 font-mono">
                    <span>Lat: {g.centre_lat?.toFixed(5)}</span>
                    <span>Lon: {g.centre_lon?.toFixed(5)}</span>
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
