import { useState, useEffect, useRef } from 'react';
import LoadingSpinner from '../shared/LoadingSpinner.jsx';
import { useRouter } from '../../router.jsx';
import { getAdminSites, uploadScada } from '../../api/sites.js';

function UploadCell({ site }) {
  const { navigate } = useRouter();
  const inputRef = useRef(null);
  const [status, setStatus] = useState(null); // null | 'uploading' | {ok, msg}

  async function handleFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    setStatus('uploading');
    try {
      const result = await uploadScada(site.id, file);
      setStatus({
        ok: true,
        msg: `${result.inverter_rows} inv · ${result.meter_rows} meter · ${result.weather_rows} weather rows`,
      });
    } catch (err) {
      setStatus({ ok: false, msg: err?.response?.data?.detail ?? 'Upload failed' });
    } finally {
      e.target.value = '';
    }
  }

  return (
    <td className="px-5 py-4">
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={() => navigate(`/site/${site.id}`)}
          className="text-xs text-slate-400 hover:text-amber-400 transition-colors"
        >
          View →
        </button>
        <input ref={inputRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={handleFile} />
        {status === 'uploading' ? (
          <span className="text-xs text-slate-400 flex items-center gap-1">
            <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
            </svg>
            Uploading…
          </span>
        ) : status?.ok ? (
          <span className="text-xs text-emerald-400">{status.msg}</span>
        ) : status?.ok === false ? (
          <span className="text-xs text-red-400">{status.msg}</span>
        ) : (
          <button
            onClick={() => inputRef.current?.click()}
            className="text-xs text-slate-400 hover:text-white border border-[#2D3F55] hover:border-slate-400 rounded px-2 py-0.5 transition-colors"
          >
            Upload Data
          </button>
        )}
      </div>
    </td>
  );
}

export default function AdminPage() {
  const { navigate } = useRouter();
  const [sites, setSites] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    getAdminSites()
      .then(setSites)
      .catch(() => setError('Failed to load sites.'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <header className="sticky top-0 z-10 flex items-center justify-between px-6 py-3 bg-[#111827] border-b border-[#2D3F55]">
        <h1 className="text-white font-semibold text-lg">Site Management</h1>
        <button
          onClick={() => navigate('/admin/onboard')}
          className="text-xs bg-amber-400 text-[#0F1629] font-semibold px-3 py-1.5 rounded-lg hover:bg-amber-300 transition-colors"
        >
          ＋ Add New Site
        </button>
      </header>

      <div className="flex-1 overflow-auto p-6">
        <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[#2D3F55]">
            <h2 className="text-white font-semibold text-sm">Sites</h2>
          </div>

          {loading ? (
            <LoadingSpinner label="Loading sites…" />
          ) : error ? (
            <p className="text-red-400 text-sm p-5">{error}</p>
          ) : sites?.length === 0 ? (
            <div className="p-10 text-center">
              <p className="text-slate-400 text-sm mb-3">No sites configured yet.</p>
              <button
                onClick={() => navigate('/admin/onboard')}
                className="text-xs bg-amber-400 text-[#0F1629] font-semibold px-4 py-2 rounded-lg hover:bg-amber-300 transition-colors"
              >
                Add New Site
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-[#2D3F55]">
                    {['Site Name', 'Capacity', 'Location', 'Inverters', 'Tilt', 'Azimuth', 'Actions'].map(h => (
                      <th key={h} className="px-5 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sites.map(site => (
                    <tr key={site.id} className="border-b border-[#2D3F55] last:border-0 hover:bg-white/5 transition-colors">
                      <td className="px-5 py-4 text-white font-medium text-sm">{site.name}</td>
                      <td className="px-5 py-4 text-slate-400 font-mono text-sm">
                        {site.capacity_kwp.toLocaleString()} kWp
                      </td>
                      <td className="px-5 py-4 text-slate-400 font-mono text-xs">
                        {site.latitude.toFixed(4)}°N, {site.longitude.toFixed(4)}°E
                      </td>
                      <td className="px-5 py-4 text-slate-400 font-mono text-sm">
                        {site.total_inverters > 0 ? `${site.total_inverters} (${site.num_inverter_groups} groups)` : '—'}
                      </td>
                      <td className="px-5 py-4 text-slate-400 font-mono text-sm">{site.tilt_deg}°</td>
                      <td className="px-5 py-4 text-slate-400 font-mono text-sm">{site.azimuth_deg}°</td>
                      <UploadCell site={site} />
                    </tr>
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
