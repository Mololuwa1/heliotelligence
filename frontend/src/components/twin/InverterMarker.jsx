// Used by GroupDetailPanel and legend — not a DOM component
export const STATUS_COLOURS = {
  normal:   [16, 185, 129],   // emerald-500
  degraded: [246, 173, 85],   // amber-400
  offline:  [239, 68, 68],    // red-500
  unknown:  [148, 163, 184],  // slate-400
};

export function statusToRgb(status) {
  return STATUS_COLOURS[status] ?? STATUS_COLOURS.unknown;
}

export function StatusLegend() {
  return (
    <div className="flex flex-col gap-2">
      {Object.entries(STATUS_COLOURS).map(([status, rgb]) => (
        <div key={status} className="flex items-center gap-2">
          <span
            className="inline-block h-3 w-3 rounded-full"
            style={{ backgroundColor: `rgb(${rgb.join(',')})` }}
          />
          <span className="text-xs text-slate-400 capitalize">{status}</span>
        </div>
      ))}
    </div>
  );
}
