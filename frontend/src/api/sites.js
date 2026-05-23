import { formatISO } from 'date-fns';
import client from './client.js';

function iso(date) {
  return formatISO(date);
}

export function getLayout(siteId) {
  return client.get(`/api/v1/sites/${siteId}/layout?demo_mode=true`).then(r => r.data);
}

export function getBenchmarking(siteId, start, end) {
  return client
    .get(`/api/v1/benchmarking/${siteId}`, { params: { start: iso(start), end: iso(end) } })
    .then(r => r.data);
}

export function getDegradation(siteId, start, end) {
  return client
    .get(`/api/v1/analysis/${siteId}/degradation`, {
      params: { start: iso(start), end: iso(end) },
    })
    .then(r => r.data);
}

export function getAnomalies(siteId, start, end) {
  return client
    .get(`/api/v1/analysis/${siteId}/anomalies`, {
      params: { start: iso(start), end: iso(end) },
    })
    .then(r => r.data);
}

export function getInverterHealth(siteId, start, end) {
  return client
    .get(`/api/v1/analysis/${siteId}/inverter-health`, {
      params: { start: iso(start), end: iso(end) },
    })
    .then(r => r.data);
}

export function getAlerts(siteId, { unacknowledgedOnly = false, limit = 50 } = {}) {
  return client
    .get(`/api/v1/alerts/${siteId}`, {
      params: { unacknowledged_only: unacknowledgedOnly, limit },
    })
    .then(r => r.data);
}

export function acknowledgeAlert(alertId) {
  return client.post(`/api/v1/alerts/${alertId}/acknowledge`).then(r => r.data);
}

export function getGeometry(siteId, maxPanelsPerGroup = 200) {
  return client
    .get(`/api/v1/sites/${siteId}/geometry?max_panels_per_group=${maxPanelsPerGroup}`)
    .then(r => r.data);
}
