import type {
  CausalGraph,
  IncidentResponse,
  Overview,
  RootCause,
  TimeSeriesResponse,
} from './types';

const BASE: string = import.meta.env.VITE_API_URL ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(`${path}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

/** The API speaks naive-UTC ISO strings; make them unambiguous. */
export function parseTime(iso: string): number {
  const hasZone = /(Z|[+-]\d\d:\d\d)$/.test(iso);
  return Date.parse(hasZone ? iso : iso + 'Z');
}

export const getOverview = () => request<Overview>('/api/overview');
export const seedDemo = () => request<{ incident_time: string }>('/demo/seed', { method: 'POST' });
export const getTimeseries = () => request<TimeSeriesResponse>('/api/timeseries');
export const getIncidents = () =>
  request<{ incidents: IncidentResponse[] }>('/api/incidents').then((r) => r.incidents);
export const getCausalGraph = () => request<CausalGraph>('/api/causal-graph');
export const getRootCause = (incidentTime: string) =>
  request<RootCause>(`/api/root-cause?incident_time=${encodeURIComponent(incidentTime)}`);
