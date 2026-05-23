import { formatDistanceToNow, parseISO } from 'date-fns';
import { acknowledgeAlert } from '../../api/sites.js';

const SEVERITY_STYLES = {
  critical: 'border-red-500/30 bg-red-500/5',
  warning:  'border-amber-400/30 bg-amber-400/5',
  info:     'border-slate-600 bg-white/5',
};

const SEVERITY_BADGE = {
  critical: 'bg-red-500/20 text-red-400',
  warning:  'bg-amber-400/20 text-amber-400',
  info:     'bg-slate-700 text-slate-400',
};

export default function AlertCard({ alert, onAcknowledged }) {
  const severity = (alert.severity ?? 'info').toLowerCase();
  const firedAt = alert.fired_at ?? alert.created_at ?? null;

  async function handleAck() {
    try {
      await acknowledgeAlert(alert.id);
      onAcknowledged?.(alert.id);
    } catch {
      // ignore — user can retry
    }
  }

  return (
    <div className={`border rounded-xl p-4 ${SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.info}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full uppercase ${SEVERITY_BADGE[severity] ?? SEVERITY_BADGE.info}`}>
              {severity}
            </span>
            <span className="text-slate-500 text-xs truncate">{alert.rule_name ?? ''}</span>
          </div>
          <p className="text-white text-sm leading-relaxed">{alert.message}</p>
          <div className="flex items-center gap-4 mt-2">
            {firedAt && (
              <span className="text-slate-500 text-xs">
                {formatDistanceToNow(parseISO(firedAt), { addSuffix: true })}
              </span>
            )}
            {alert.metric_value != null && (
              <span className="text-slate-500 text-xs font-mono">
                value: {alert.metric_value.toFixed?.(3) ?? alert.metric_value}
                {alert.threshold != null && ` / threshold: ${alert.threshold}`}
              </span>
            )}
          </div>
        </div>

        {!alert.acknowledged && (
          <button
            onClick={handleAck}
            className="flex-shrink-0 text-xs text-slate-400 hover:text-white border border-[#2D3F55] hover:border-white/30 rounded-lg px-3 py-1.5 transition-colors"
          >
            Acknowledge
          </button>
        )}
        {alert.acknowledged && (
          <span className="flex-shrink-0 text-xs text-emerald-400 px-2">✓ ack</span>
        )}
      </div>
    </div>
  );
}
