import type { Metric } from './types';

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

export const formatClock = (ms: number) => timeFmt.format(ms);
export const formatDateTime = (ms: number) => dateTimeFmt.format(ms);

export function formatRelative(minutes: number): string {
  if (minutes === 0) return 'T+0m';
  const sign = minutes > 0 ? '+' : '−';
  const abs = Math.abs(minutes);
  return abs >= 60
    ? `T${sign}${Math.floor(abs / 60)}h${String(abs % 60).padStart(2, '0')}m`
    : `T${sign}${abs}m`;
}

export const METRIC_LABELS: Record<Metric, string> = {
  latency_p99: 'Latency p99',
  error_rate: 'Error rate',
  throughput: 'Throughput',
};

export function formatMetric(metric: Metric, value: number): string {
  switch (metric) {
    case 'latency_p99':
      return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
    case 'error_rate':
      return `${(value * 100).toFixed(value < 0.01 ? 1 : 0)}%`;
    case 'throughput':
      return `${Math.round(value)}/min`;
  }
}

export function formatMetricName(metric: string): string {
  return METRIC_LABELS[metric as Metric] ?? metric;
}
