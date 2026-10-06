export type Health = 'healthy' | 'degraded' | 'critical';
export type Metric = 'latency_p99' | 'error_rate' | 'throughput';

export interface Overview {
  seeded: boolean;
  services?: string[];
  window_start?: string;
  window_end?: string;
  baseline_end?: string;
  default_incident_time?: string;
  bucket_minutes?: number;
  graph_ready?: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  lag_minutes: number;
  f_statistic: number;
  p_value: number;
  strength: number;
  metrics: string[];
}

export interface CausalGraph {
  nodes: string[];
  edges: GraphEdge[];
}

export interface ChainLink {
  source: string;
  target: string;
  lag_minutes: number;
  f_statistic: number;
  metrics: string[];
}

export interface RootCause {
  status: 'ROOT_CAUSE_IDENTIFIED' | 'NO_ANOMALY' | 'INDEPENDENT_FAILURES';
  incident_time: string;
  root_cause: string | null;
  confidence: number | null;
  causal_chain: ChainLink[];
  anomalous_services: string[];
  total_propagation_minutes: number | null;
  message: string | null;
}

export interface ServiceSeries {
  latency_p99: number[];
  error_rate: number[];
  throughput: number[];
  anomaly_score: number[];
  health: Health[];
}

export interface TimeSeriesResponse {
  timestamps: string[];
  services: Record<string, ServiceSeries>;
}

export interface IncidentResponse {
  start: string;
  end: string;
  services: string[];
}

/** Time series with timestamps parsed to epoch ms. */
export interface Series {
  times: number[];
  services: Record<string, ServiceSeries>;
}

/** Incident with times resolved to indexes into Series.times. */
export interface Incident {
  start: number;
  end: number; // exclusive
  startTime: string; // as the API reported it, for root-cause requests
  services: string[];
}
