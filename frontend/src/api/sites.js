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

export function generateReport(siteId, start, end) {
  return client.post(
    `/api/v1/reports/${siteId}`,
    null,
    { params: { start: iso(start), end: iso(end) }, responseType: 'blob' },
  );
}

const ADMIN_KEY = import.meta.env.VITE_ADMIN_KEY ?? ''

export function getAdminSites() {
  return client.get('/api/v1/admin/sites', {
    headers: { 'X-Admin-Key': ADMIN_KEY },
  }).then(r => r.data)
}

export function createSite(data) {
  return client.post('/api/v1/admin/sites', data, {
    headers: { 'X-Admin-Key': ADMIN_KEY },
  }).then(r => r.data)
}

export function uploadScada(siteId, file) {
  const form = new FormData()
  form.append('file', file)
  return client.post(`/api/v1/admin/sites/${siteId}/upload`, form, {
    headers: { 'Content-Type': 'multipart/form-data', 'X-Admin-Key': ADMIN_KEY },
    timeout: 300000,
  }).then(r => r.data)
}
