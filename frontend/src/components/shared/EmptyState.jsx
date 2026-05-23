export default function EmptyState({ title = 'No data', message = '' }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-slate-400">
      <svg
        className="h-10 w-10 text-slate-600"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
      <p className="text-sm font-medium text-slate-300">{title}</p>
      {message && <p className="text-xs text-slate-500 max-w-xs text-center">{message}</p>}
    </div>
  );
}
