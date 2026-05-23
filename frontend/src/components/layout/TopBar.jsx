import { useTimeRange, PRESETS } from '../../contexts/TimeRangeContext.jsx';

export default function TopBar({ title, onRefresh }) {
  const { preset, setPreset } = useTimeRange();

  return (
    <header className="sticky top-0 z-10 flex items-center justify-between px-6 py-3 bg-[#111827] border-b border-[#2D3F55]">
      <h1 className="text-white font-semibold text-lg">{title}</h1>

      <div className="flex items-center gap-3">
        {/* Time range selector */}
        <div className="flex items-center bg-[#1E2A3A] border border-[#2D3F55] rounded-lg p-1 gap-0.5">
          {PRESETS.map(p => (
            <button
              key={p.key}
              onClick={() => setPreset(p)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                preset.key === p.key
                  ? 'bg-amber-400 text-[#0F1629]'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Refresh */}
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="p-2 rounded-lg bg-[#1E2A3A] border border-[#2D3F55] text-slate-400 hover:text-white transition-colors"
            title="Refresh"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
          </button>
        )}
      </div>
    </header>
  );
}
