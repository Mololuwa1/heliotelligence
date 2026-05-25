import { useState, useRef } from 'react';
import { useRouter } from '../../router.jsx';
import { createSite, uploadScada } from '../../api/sites.js';

const STEPS = ['Site Details', 'Technical Config', 'Inverter Layout', 'Review'];

const TIMEZONES = [
  'Europe/London', 'Europe/Berlin', 'Europe/Paris',
  'America/New_York', 'America/Chicago', 'America/Los_Angeles',
  'Asia/Dubai', 'Asia/Singapore', 'Australia/Sydney',
];

const INIT = {
  name: '', latitude: '', longitude: '', altitude_m: '0', timezone: 'Europe/London',
  capacity_kwp: '', tilt_deg: '15', azimuth_deg: '0', gcr: '0.4',
  row_pitch_m: '6.0', pvsyst_pr_target_pct: '',
  modules_per_string: '24', num_strings: '',
  soiling_loss_pct: '1.0', lid_loss_pct: '0.6',
  inverter_model: '', num_inverters: '',
  inverter_pnom_kwac: '350', inverter_eta_nom: '98.4',
  grid_limit_kwac: '',
  inverter_groups: [],
};

function Field({ label, required, error, children }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1">
        {label}{required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      {children}
      {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
    </div>
  );
}

function Input({ value, onChange, type = 'text', min, max, step, placeholder, className = '' }) {
  return (
    <input
      type={type}
      value={value}
      onChange={e => onChange(e.target.value)}
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      className={`w-full bg-[#0F1629] border rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-amber-400 ${
        className || 'border-[#2D3F55]'
      }`}
    />
  );
}

function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full bg-[#0F1629] border border-[#2D3F55] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-amber-400"
    >
      {options.map(o => (
        <option key={o} value={o}>{o}</option>
      ))}
    </select>
  );
}

function ProgressBar({ step }) {
  return (
    <div className="flex items-center gap-0 mb-8">
      {STEPS.map((label, i) => (
        <div key={i} className="flex items-center flex-1 last:flex-none">
          <div className="flex flex-col items-center">
            <div className={`h-8 w-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-colors ${
              i < step ? 'bg-amber-400 border-amber-400 text-[#0F1629]'
              : i === step ? 'border-amber-400 text-amber-400'
              : 'border-[#2D3F55] text-slate-500'
            }`}>
              {i < step ? '✓' : i + 1}
            </div>
            <span className={`text-xs mt-1 whitespace-nowrap ${i === step ? 'text-amber-400' : 'text-slate-500'}`}>
              {label}
            </span>
          </div>
          {i < STEPS.length - 1 && (
            <div className={`flex-1 h-px mx-2 mb-4 ${i < step ? 'bg-amber-400' : 'bg-[#2D3F55]'}`} />
          )}
        </div>
      ))}
    </div>
  );
}

function Step1({ form, set, errors }) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="col-span-2">
        <Field label="Site Name" required error={errors.name}>
          <Input value={form.name} onChange={v => set('name', v)}
            placeholder="e.g. Suffolk Solar Farm"
            className={errors.name ? 'border-red-400' : 'border-[#2D3F55]'}
          />
        </Field>
      </div>
      <Field label="Latitude" required error={errors.latitude}>
        <Input type="number" value={form.latitude} onChange={v => set('latitude', v)}
          min={-90} max={90} step="0.000001" placeholder="52.560000"
          className={errors.latitude ? 'border-red-400' : 'border-[#2D3F55]'}
        />
      </Field>
      <Field label="Longitude" required error={errors.longitude}>
        <Input type="number" value={form.longitude} onChange={v => set('longitude', v)}
          min={-180} max={180} step="0.000001" placeholder="1.210000"
          className={errors.longitude ? 'border-red-400' : 'border-[#2D3F55]'}
        />
      </Field>
      <Field label="Altitude (m)">
        <Input type="number" value={form.altitude_m} onChange={v => set('altitude_m', v)} min={0} />
      </Field>
      <Field label="Timezone" required>
        <Select value={form.timezone} onChange={v => set('timezone', v)} options={TIMEZONES} />
      </Field>
    </div>
  );
}

function Step2({ form, set, errors }) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="DC Capacity (kWp)" required error={errors.capacity_kwp}>
        <Input type="number" value={form.capacity_kwp} onChange={v => set('capacity_kwp', v)}
          min={0} step="0.1" placeholder="28524"
          className={errors.capacity_kwp ? 'border-red-400' : 'border-[#2D3F55]'}
        />
      </Field>
      <Field label="Total Strings" required error={errors.num_strings}>
        <Input type="number" value={form.num_strings} onChange={v => set('num_strings', v)}
          min={1} placeholder="2076"
          className={errors.num_strings ? 'border-red-400' : 'border-[#2D3F55]'}
        />
      </Field>
      <Field label="Tilt (°)" required>
        <Input type="number" value={form.tilt_deg} onChange={v => set('tilt_deg', v)} min={0} max={90} />
      </Field>
      <Field label="Azimuth (°) — PVsyst: 0=South">
        <Input type="number" value={form.azimuth_deg} onChange={v => set('azimuth_deg', v)} min={-180} max={180} />
      </Field>
      <Field label="GCR">
        <Input type="number" value={form.gcr} onChange={v => set('gcr', v)} min={0} max={1} step="0.01" />
      </Field>
      <Field label="Row Pitch (m)">
        <Input type="number" value={form.row_pitch_m} onChange={v => set('row_pitch_m', v)} min={0} step="0.1" />
      </Field>
      <Field label="Modules / String">
        <Input type="number" value={form.modules_per_string} onChange={v => set('modules_per_string', v)} min={1} />
      </Field>
      <Field label="Target PR (%)">
        <Input type="number" value={form.pvsyst_pr_target_pct} onChange={v => set('pvsyst_pr_target_pct', v)}
          min={0} max={100} step="0.01" placeholder="86.56" />
      </Field>
      <Field label="Soiling Loss (%)">
        <Input type="number" value={form.soiling_loss_pct} onChange={v => set('soiling_loss_pct', v)} min={0} step="0.1" />
      </Field>
      <Field label="LID Loss (%)">
        <Input type="number" value={form.lid_loss_pct} onChange={v => set('lid_loss_pct', v)} min={0} step="0.01" />
      </Field>
    </div>
  );
}

function Step3({ form, set, errors }) {
  function addGroup() {
    set('inverter_groups', [...form.inverter_groups, {
      id: '', label: '', centre_lat: '', centre_lon: '', inverter_count: '', inverter_id_prefix: '',
    }]);
  }

  function removeGroup(i) {
    set('inverter_groups', form.inverter_groups.filter((_, idx) => idx !== i));
  }

  function updateGroup(i, field, val) {
    const updated = form.inverter_groups.map((g, idx) => idx === i ? { ...g, [field]: val } : g);
    set('inverter_groups', updated);
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <Field label="Inverter Model">
          <Input value={form.inverter_model} onChange={v => set('inverter_model', v)} placeholder="e.g. Sungrow SG350HX" />
        </Field>
        <Field label="Number of Inverters" required error={errors.num_inverters}>
          <Input type="number" value={form.num_inverters} onChange={v => set('num_inverters', v)}
            min={1} placeholder="66"
            className={errors.num_inverters ? 'border-red-400' : 'border-[#2D3F55]'}
          />
        </Field>
        <Field label="Inverter Power (kWac)" required>
          <Input type="number" value={form.inverter_pnom_kwac} onChange={v => set('inverter_pnom_kwac', v)} min={0} step="0.1" />
        </Field>
        <Field label="Efficiency (%)">
          <Input type="number" value={form.inverter_eta_nom} onChange={v => set('inverter_eta_nom', v)} min={0} max={100} step="0.01" />
        </Field>
        <Field label="Grid Limit (kWac)">
          <Input type="number" value={form.grid_limit_kwac} onChange={v => set('grid_limit_kwac', v)} min={0} placeholder="Optional" />
        </Field>
      </div>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-white font-medium text-sm">Inverter Groups</h3>
          <button
            onClick={addGroup}
            className="text-xs text-amber-400 border border-amber-400/30 rounded px-2 py-1 hover:bg-amber-400/10 transition-colors"
          >
            + Add Group
          </button>
        </div>

        {form.inverter_groups.length === 0 ? (
          <p className="text-slate-500 text-sm text-center py-4 border border-dashed border-[#2D3F55] rounded-lg">
            No groups added. Click "+ Add Group" or leave empty.
          </p>
        ) : (
          <div className="space-y-3">
            {form.inverter_groups.map((g, i) => (
              <div key={i} className="bg-[#0F1629] border border-[#2D3F55] rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-white text-xs font-medium">Group {i + 1}</span>
                  <button onClick={() => removeGroup(i)} className="text-red-400 text-xs hover:text-red-300">Remove</button>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <Field label="Group ID" required>
                    <Input value={g.id} onChange={v => updateGroup(i, 'id', v)} placeholder="INV01" />
                  </Field>
                  <Field label="Label">
                    <Input value={g.label} onChange={v => updateGroup(i, 'label', v)} placeholder="Block INV01" />
                  </Field>
                  <Field label="Inverter Count" required>
                    <Input type="number" value={g.inverter_count} onChange={v => updateGroup(i, 'inverter_count', v)} min={1} />
                  </Field>
                  <Field label="Centre Lat" required>
                    <Input type="number" value={g.centre_lat} onChange={v => updateGroup(i, 'centre_lat', v)} step="0.000001" />
                  </Field>
                  <Field label="Centre Lon" required>
                    <Input type="number" value={g.centre_lon} onChange={v => updateGroup(i, 'centre_lon', v)} step="0.000001" />
                  </Field>
                  <Field label="ID Prefix" required>
                    <Input value={g.inverter_id_prefix} onChange={v => updateGroup(i, 'inverter_id_prefix', v)} placeholder="INV01-TB" />
                  </Field>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ReviewRow({ label, value }) {
  return (
    <div className="flex justify-between py-1.5 border-b border-[#1E2A3A] last:border-0">
      <span className="text-slate-400 text-xs">{label}</span>
      <span className="text-white text-xs font-mono">{value ?? '—'}</span>
    </div>
  );
}

function Step4({ form }) {
  return (
    <div className="space-y-5">
      <div className="bg-[#0F1629] border border-[#1E2A3A] rounded-xl overflow-hidden">
        <div className="px-4 py-2 border-b border-[#1E2A3A]">
          <h3 className="text-amber-400 text-xs font-bold uppercase tracking-widest">Site Configuration</h3>
        </div>
        <div className="px-4 py-1">
          <ReviewRow label="Name" value={form.name} />
          <ReviewRow label="Latitude" value={`${form.latitude}°N`} />
          <ReviewRow label="Longitude" value={`${form.longitude}°E`} />
          <ReviewRow label="Timezone" value={form.timezone} />
          <ReviewRow label="DC Capacity" value={`${Number(form.capacity_kwp).toLocaleString()} kWp`} />
          <ReviewRow label="Tilt" value={`${form.tilt_deg}°`} />
          <ReviewRow label="Azimuth" value={`${form.azimuth_deg}° (PVsyst)`} />
          <ReviewRow label="Total Strings" value={form.num_strings} />
          <ReviewRow label="Target PR" value={form.pvsyst_pr_target_pct ? `${form.pvsyst_pr_target_pct}%` : null} />
          <ReviewRow label="Number of Inverters" value={form.num_inverters} />
          <ReviewRow label="Inverter Power" value={form.inverter_pnom_kwac ? `${form.inverter_pnom_kwac} kWac` : null} />
          <ReviewRow label="Grid Limit" value={form.grid_limit_kwac ? `${form.grid_limit_kwac} kWac` : null} />
        </div>
      </div>

      {form.inverter_groups.length > 0 && (
        <div className="bg-[#0F1629] border border-[#1E2A3A] rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-[#1E2A3A]">
            <h3 className="text-amber-400 text-xs font-bold uppercase tracking-widest">Inverter Groups</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#1E2A3A]">
                  {['ID', 'Label', 'Inverters', 'Prefix'].map(h => (
                    <th key={h} className="px-4 py-2 text-left text-slate-500 font-medium uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {form.inverter_groups.map((g, i) => (
                  <tr key={i} className="border-b border-[#1E2A3A] last:border-0">
                    <td className="px-4 py-2 text-white font-mono">{g.id}</td>
                    <td className="px-4 py-2 text-slate-400">{g.label || '—'}</td>
                    <td className="px-4 py-2 text-slate-400">{g.inverter_count}</td>
                    <td className="px-4 py-2 text-slate-400 font-mono">{g.inverter_id_prefix}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function SuccessScreen({ siteId, siteName }) {
  const { navigate } = useRouter();
  const inputRef = useRef(null);
  const [uploadState, setUploadState] = useState(null); // null | 'uploading' | {ok, result} | {ok: false, msg}

  async function handleDrop(e) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) await doUpload(file);
  }

  async function handleFile(e) {
    const file = e.target.files[0];
    if (file) await doUpload(file);
  }

  async function doUpload(file) {
    setUploadState('uploading');
    try {
      const result = await uploadScada(siteId, file);
      setUploadState({ ok: true, result });
    } catch (err) {
      setUploadState({ ok: false, msg: err?.response?.data?.detail ?? 'Upload failed' });
    }
  }

  return (
    <div className="text-center space-y-6">
      <div className="flex flex-col items-center gap-3">
        <div className="h-16 w-16 rounded-full bg-emerald-400/10 flex items-center justify-center">
          <svg className="h-8 w-8 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h2 className="text-white text-xl font-semibold">Site created successfully!</h2>
        <p className="text-slate-400 text-sm">{siteName}</p>
        <p className="text-slate-500 text-xs font-mono">{siteId}</p>
      </div>

      <div
        onDragOver={e => e.preventDefault()}
        onDrop={handleDrop}
        className="border-2 border-dashed border-[#2D3F55] rounded-xl p-8 hover:border-amber-400/40 transition-colors"
      >
        <input ref={inputRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={handleFile} />
        {uploadState === null && (
          <>
            <p className="text-slate-400 text-sm mb-3">Upload SCADA Data</p>
            <p className="text-slate-500 text-xs mb-4">Drag & drop a CSV or Excel file, or click to browse</p>
            <button
              onClick={() => inputRef.current?.click()}
              className="text-xs bg-[#1E2A3A] border border-[#2D3F55] text-white px-4 py-2 rounded-lg hover:border-amber-400/40 transition-colors"
            >
              Browse File
            </button>
          </>
        )}
        {uploadState === 'uploading' && (
          <div className="flex items-center justify-center gap-2 text-slate-400 text-sm">
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
            </svg>
            Uploading…
          </div>
        )}
        {uploadState?.ok === true && (
          <div className="space-y-2">
            <p className="text-emerald-400 text-sm font-medium">Upload complete</p>
            <div className="text-slate-400 text-xs font-mono space-y-1">
              <p>Weather rows: {uploadState.result.weather_rows}</p>
              <p>Meter rows: {uploadState.result.meter_rows}</p>
              <p>Inverter rows: {uploadState.result.inverter_rows}</p>
              <p>String rows: {uploadState.result.string_rows}</p>
            </div>
          </div>
        )}
        {uploadState?.ok === false && (
          <div className="space-y-3">
            <p className="text-red-400 text-sm">{uploadState.msg}</p>
            <button
              onClick={() => { setUploadState(null); }}
              className="text-xs text-slate-400 hover:text-white"
            >
              Try again
            </button>
          </div>
        )}
      </div>

      <div className="flex gap-3 justify-center">
        <button
          onClick={() => navigate(`/site/${siteId}`)}
          className="text-sm bg-amber-400 text-[#0F1629] font-semibold px-5 py-2 rounded-lg hover:bg-amber-300 transition-colors"
        >
          View Site Dashboard →
        </button>
        <button
          onClick={() => window.location.reload()}
          className="text-sm border border-[#2D3F55] text-slate-400 px-5 py-2 rounded-lg hover:text-white hover:border-slate-400 transition-colors"
        >
          Add Another Site
        </button>
      </div>
    </div>
  );
}

export default function OnboardingWizard() {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState(INIT);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [created, setCreated] = useState(null); // {siteId, siteName}

  function set(key, val) {
    setForm(f => ({ ...f, [key]: val }));
    setErrors(e => ({ ...e, [key]: undefined }));
  }

  function validate() {
    const errs = {};
    if (step === 0) {
      if (!form.name || form.name.length < 2) errs.name = 'Required (min 2 characters)';
      if (form.latitude === '' || isNaN(Number(form.latitude))) errs.latitude = 'Required';
      if (form.longitude === '' || isNaN(Number(form.longitude))) errs.longitude = 'Required';
    }
    if (step === 1) {
      if (!form.capacity_kwp || isNaN(Number(form.capacity_kwp))) errs.capacity_kwp = 'Required';
      if (!form.num_strings || isNaN(Number(form.num_strings))) errs.num_strings = 'Required';
    }
    if (step === 2) {
      if (!form.num_inverters || isNaN(Number(form.num_inverters))) errs.num_inverters = 'Required';
    }
    return errs;
  }

  function next() {
    const errs = validate();
    if (Object.keys(errs).length > 0) { setErrors(errs); return; }
    setStep(s => s + 1);
  }

  function back() {
    setStep(s => s - 1);
    setErrors({});
  }

  async function submit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const payload = {
        name: form.name,
        latitude: Number(form.latitude),
        longitude: Number(form.longitude),
        altitude_m: Number(form.altitude_m) || 0,
        timezone: form.timezone,
        capacity_kwp: Number(form.capacity_kwp),
        tilt_deg: Number(form.tilt_deg),
        azimuth_deg: Number(form.azimuth_deg),
        gcr: Number(form.gcr),
        row_pitch_m: Number(form.row_pitch_m),
        modules_per_string: Number(form.modules_per_string),
        num_strings: Number(form.num_strings),
        soiling_loss_pct: Number(form.soiling_loss_pct),
        lid_loss_pct: Number(form.lid_loss_pct),
        inverter_model: form.inverter_model,
        num_inverters: Number(form.num_inverters),
        inverter_pnom_kwac: Number(form.inverter_pnom_kwac),
        inverter_eta_nom: Number(form.inverter_eta_nom) / 100,
        wiring_loss_ac_pct: 1.70,
        inverter_groups: form.inverter_groups.map(g => ({
          id: g.id,
          label: g.label || g.id,
          centre_lat: Number(g.centre_lat),
          centre_lon: Number(g.centre_lon),
          inverter_count: Number(g.inverter_count),
          inverter_id_prefix: g.inverter_id_prefix,
        })),
      };
      if (form.pvsyst_pr_target_pct) payload.pvsyst_pr_target_pct = Number(form.pvsyst_pr_target_pct);
      if (form.grid_limit_kwac) payload.grid_limit_kwac = Number(form.grid_limit_kwac);

      const result = await createSite(payload);
      setCreated({ siteId: result.site_id, siteName: result.name });
    } catch (err) {
      setSubmitError(err?.response?.data?.detail ?? 'Failed to create site. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  if (created) {
    return (
      <div className="flex-1 flex flex-col min-h-0">
        <header className="sticky top-0 z-10 flex items-center px-6 py-3 bg-[#111827] border-b border-[#2D3F55]">
          <h1 className="text-white font-semibold text-lg">Add New Site</h1>
        </header>
        <div className="flex-1 overflow-auto p-6">
          <div className="max-w-xl mx-auto">
            <SuccessScreen siteId={created.siteId} siteName={created.siteName} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <header className="sticky top-0 z-10 flex items-center px-6 py-3 bg-[#111827] border-b border-[#2D3F55]">
        <h1 className="text-white font-semibold text-lg">Add New Site</h1>
      </header>

      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-2xl mx-auto">
          <ProgressBar step={step} />

          <div className="bg-[#1E2A3A] border border-[#2D3F55] rounded-xl p-6">
            <h2 className="text-white font-semibold text-base mb-5">{STEPS[step]}</h2>

            {step === 0 && <Step1 form={form} set={set} errors={errors} />}
            {step === 1 && <Step2 form={form} set={set} errors={errors} />}
            {step === 2 && <Step3 form={form} set={set} errors={errors} />}
            {step === 3 && <Step4 form={form} />}

            {submitError && (
              <p className="text-red-400 text-sm mt-4">{submitError}</p>
            )}

            <div className="flex justify-between mt-6">
              {step > 0 ? (
                <button
                  onClick={back}
                  className="text-sm border border-[#2D3F55] text-slate-400 px-5 py-2 rounded-lg hover:text-white hover:border-slate-400 transition-colors"
                >
                  Back
                </button>
              ) : <div />}

              {step < STEPS.length - 1 ? (
                <button
                  onClick={next}
                  className="text-sm bg-amber-400 text-[#0F1629] font-semibold px-5 py-2 rounded-lg hover:bg-amber-300 transition-colors"
                >
                  Next →
                </button>
              ) : (
                <button
                  onClick={submit}
                  disabled={submitting}
                  className="text-sm bg-amber-400 text-[#0F1629] font-semibold px-5 py-2 rounded-lg hover:bg-amber-300 transition-colors disabled:opacity-50"
                >
                  {submitting ? 'Creating…' : 'Create Site'}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
