const COLOURS = {
  normal: 'bg-emerald-400',
  degraded: 'bg-amber-400',
  offline: 'bg-red-400',
  unknown: 'bg-slate-500',
  active: 'bg-emerald-400',
  warning: 'bg-amber-400',
  critical: 'bg-red-400',
};

export default function StatusDot({ status = 'unknown', size = 'md' }) {
  const sizeClass = size === 'sm' ? 'h-2 w-2' : 'h-2.5 w-2.5';
  const colour = COLOURS[status] ?? 'bg-slate-500';
  return <span className={`inline-block rounded-full ${sizeClass} ${colour}`} />;
}
