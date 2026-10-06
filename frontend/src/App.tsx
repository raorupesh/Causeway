import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as api from './api';
import { CausalGraph } from './components/CausalGraph';
import { ReplayControls, type Mode } from './components/ReplayControls';
import { RootCausePanel, type Phase } from './components/RootCausePanel';
import { Timeline } from './components/Timeline';
import { METRIC_LABELS } from './format';
import type {
  CausalGraph as Graph,
  Health,
  Incident,
  Metric,
  Overview,
  RootCause,
  Series,
} from './types';

const SPANS = { '2h': 120, '6h': 360, '24h': 1440 } as const;
type SpanKey = keyof typeof SPANS;

/** Minutes of quiet shown before an incident when replay starts. */
const PRE_ROLL = 8;
/** Real milliseconds per simulated minute at 1× speed. */
const TICK_MS = 700;

export default function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [series, setSeries] = useState<Series | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [incidentIdx, setIncidentIdx] = useState(0);
  const [report, setReport] = useState<RootCause | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const [mode, setMode] = useState<Mode>('replay');
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2);
  const [metric, setMetric] = useState<Metric>('latency_p99');
  const [spanKey, setSpanKey] = useState<SpanKey>('2h');
  const [viewStart, setViewStart] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  // -- loading -------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setGraph(null);
    setReport(null);

    (async () => {
      try {
        const ov = await api.getOverview();
        if (cancelled) return;
        setOverview(ov);
        if (!ov.seeded) return;

        const [ts, rawIncidents] = await Promise.all([api.getTimeseries(), api.getIncidents()]);
        if (cancelled) return;
        const times = ts.timestamps.map(api.parseTime);
        const indexOf = (iso: string) =>
          Math.max(
            0,
            Math.min(times.length - 1, Math.round((api.parseTime(iso) - times[0]) / 60000)),
          );
        const parsed: Incident[] = rawIncidents.map((i) => ({
          start: indexOf(i.start),
          end: Math.min(indexOf(i.end), times.length),
          startTime: i.start,
          services: i.services,
        }));
        // Default to the incident that touched the most services.
        const main = parsed.reduce(
          (best, inc, i) => (inc.services.length > parsed[best].services.length ? i : best),
          0,
        );

        setSeries({ times, services: ts.services });
        setIncidents(parsed);
        setIncidentIdx(main);
        setMode('replay');
        setPlaying(false);
        // ?t=<minutes> deep-links to a replay position relative to the incident.
        const t = Number(new URLSearchParams(window.location.search).get('t') ?? NaN);
        const offset = Number.isFinite(t) ? Math.round(t) : -PRE_ROLL;
        setCursor(
          parsed.length
            ? Math.max(0, Math.min(times.length - 1, parsed[main].start + offset))
            : times.length - 1,
        );

        const g = await api.getCausalGraph();
        if (!cancelled) setGraph(g);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const incident = incidents[incidentIdx] ?? null;

  useEffect(() => {
    if (!incident) return;
    let cancelled = false;
    setReport(null);
    setReportError(null);
    api
      .getRootCause(incident.startTime)
      .then((r) => !cancelled && setReport(r))
      .catch((e) => !cancelled && setReportError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [incident]);

  const seed = async () => {
    setSeeding(true);
    setError(null);
    try {
      await api.seedDemo();
      setReloadKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSeeding(false);
    }
  };

  // -- playback ------------------------------------------------------------

  const n = series?.times.length ?? 0;

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => setCursor((c) => Math.min(c + 1, n - 1)), TICK_MS / speed);
    return () => window.clearInterval(id);
  }, [playing, speed, n]);

  useEffect(() => {
    if (playing && cursor >= n - 1) setPlaying(false);
  }, [playing, cursor, n]);

  const seek = useCallback(
    (index: number) => {
      setMode('replay');
      setCursor(Math.max(0, Math.min(n - 1, index)));
    },
    [n],
  );

  const goLive = () => {
    setMode('live');
    setPlaying(false);
    setCursor(n - 1);
  };

  const restart = useCallback(() => {
    if (!incident) return;
    seek(incident.start - PRE_ROLL);
  }, [incident, seek]);

  const togglePlay = useCallback(() => {
    if (playing) return setPlaying(false);
    setMode('replay');
    // Pressing play at the very end restarts the incident replay.
    if (cursor >= n - 1 && incident) setCursor(Math.max(0, incident.start - PRE_ROLL));
    setPlaying(true);
  }, [playing, cursor, n, incident]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!series || (e.target as HTMLElement).closest('input, select, textarea')) return;
      if (e.key === ' ') {
        e.preventDefault();
        togglePlay();
      } else if (e.key === 'ArrowLeft') {
        setPlaying(false);
        seek(cursor - (e.shiftKey ? 10 : 1));
      } else if (e.key === 'ArrowRight') {
        setPlaying(false);
        seek(cursor + (e.shiftKey ? 10 : 1));
      } else if (e.key === 'Escape') {
        setSelected(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [series, togglePlay, seek, cursor]);

  // Keep the cursor inside the visible timeline window, re-anchoring the
  // window only when the cursor leaves it (so playback doesn't jitter).
  const span = Math.min(SPANS[spanKey], Math.max(n, 1));
  const prevSpan = useRef(span);
  useEffect(() => {
    if (!n) return;
    const maxStart = Math.max(0, n - span);
    const anchor = () => Math.max(0, Math.min(maxStart, cursor - Math.floor(span * 0.2)));
    if (prevSpan.current !== span) {
      prevSpan.current = span;
      setViewStart(anchor());
    } else if (cursor < viewStart || cursor > viewStart + span - 1) {
      setViewStart(anchor());
    } else if (viewStart > maxStart) {
      setViewStart(maxStart);
    }
  }, [cursor, span, n, viewStart]);

  // -- derived state at the cursor ----------------------------------------

  const services = useMemo(() => (series ? Object.keys(series.services) : []), [series]);

  const onsets = useMemo(() => {
    const result: Record<string, number | null> = {};
    if (!series || !incident) return result;
    for (const s of services) {
      const h = series.services[s].health;
      let onset: number | null = null;
      for (let i = incident.start; i < incident.end; i++) {
        if (h[i] !== 'healthy') {
          onset = i;
          break;
        }
      }
      result[s] = onset;
    }
    return result;
  }, [series, incident, services]);

  // Lay services out in the order the incident reached them.
  const order = useMemo(
    () =>
      [...services].sort((a, b) => {
        const oa = onsets[a] ?? Infinity;
        const ob = onsets[b] ?? Infinity;
        return oa === ob ? a.localeCompare(b) : oa - ob;
      }),
    [services, onsets],
  );

  const healthAt = useMemo(() => {
    const h: Record<string, Health> = {};
    if (series) for (const s of services) h[s] = series.services[s].health[cursor];
    return h;
  }, [series, services, cursor]);

  const phase: Phase = !incident
    ? 'before'
    : cursor < incident.start
      ? 'before'
      : cursor < incident.end
        ? 'active'
        : 'resolved';

  const chain = report?.status === 'ROOT_CAUSE_IDENTIFIED' ? report.causal_chain : [];
  const rootCause = report?.status === 'ROOT_CAUSE_IDENTIFIED' ? report.root_cause : null;
  // The root cause is "found" once any service in the incident is critical,
  // i.e. once the anomaly is sustained rather than a one-minute blip.
  const rootVisible =
    phase === 'resolved' ||
    (phase === 'active' &&
      !!series &&
      services.some((s) =>
        series.services[s].health.slice(incident!.start, cursor + 1).includes('critical'),
      ));
  const revealed =
    phase === 'resolved'
      ? chain.length
      : rootVisible
        ? chain.filter((l) => onsets[l.target] !== null && onsets[l.target]! <= cursor).length
        : 0;

  // -- render --------------------------------------------------------------

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" className="brand__mark" aria-hidden>
            <circle cx="8" cy="8" r="4.5" />
            <circle cx="24" cy="16" r="4.5" />
            <circle cx="8" cy="24" r="4.5" />
            <path d="M12 10 L20 14 M20 18 L12 22" />
          </svg>
          <div>
            <h1>Causeway</h1>
            <p>Datadog shows you what broke. Causeway shows you why.</p>
          </div>
        </div>

        <div className="topbar__actions">
          {series && (
            <div className="segmented" role="group" aria-label="Mode">
              <button className={mode === 'live' ? 'is-active' : ''} onClick={goLive}>
                <span className="live-dot" /> Live
              </button>
              <button className={mode === 'replay' ? 'is-active' : ''} onClick={restart}>
                Replay
              </button>
            </div>
          )}
          {overview?.seeded && (
            <button className="btn" onClick={seed} disabled={seeding}>
              {seeding ? 'Generating…' : 'Regenerate demo data'}
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="banner banner--error">
          <strong>Couldn’t reach the Causeway API.</strong> {error}
          <button className="btn btn--small" onClick={() => setReloadKey((k) => k + 1)}>
            Retry
          </button>
        </div>
      )}

      {overview && !overview.seeded && (
        <div className="empty">
          <h2>No traces yet</h2>
          <p>
            Generate 24 hours of synthetic traffic across five services, with a planted
            database-pool exhaustion that cascades through the system. Causeway learns the causal
            structure from the first 22 hours and then explains the incident.
          </p>
          <button className="btn btn--primary" onClick={seed} disabled={seeding}>
            {seeding ? (
              <>
                <span className="spinner" /> Generating traces…
              </>
            ) : (
              'Generate demo data'
            )}
          </button>
        </div>
      )}

      {!overview && !error && (
        <div className="empty">
          <p className="panel__muted">
            <span className="spinner" /> Connecting…
          </p>
        </div>
      )}

      {series && (
        <main className="layout">
          <section className="card card--graph">
            <header className="card__header">
              <h2>Causal graph</h2>
              <span className="card__meta">
                {graph
                  ? `${graph.nodes.length} services · ${graph.edges.length} Granger-causal edges`
                  : 'learning…'}
              </span>
            </header>
            {graph ? (
              <CausalGraph
                nodes={graph.nodes}
                edges={graph.edges}
                order={order}
                health={healthAt}
                chain={rootVisible ? chain : []}
                revealed={revealed}
                rootCause={rootVisible ? rootCause : null}
                selected={selected}
                onSelect={setSelected}
              />
            ) : (
              <div className="graph graph--loading">
                <span className="spinner" />
                <p>Running Granger causality tests across every service pair…</p>
              </div>
            )}
          </section>

          <RootCausePanel
            times={series.times}
            cursor={cursor}
            incidents={incidents}
            incidentIdx={incidentIdx}
            onSelectIncident={(i) => {
              setIncidentIdx(i);
              setPlaying(false);
              seek(incidents[i].start - PRE_ROLL);
            }}
            phase={phase}
            report={report}
            reportError={reportError}
            onsets={onsets}
            revealed={revealed}
            rootVisible={rootVisible}
            serviceCount={services.length}
            onSelectService={(s) => setSelected((cur) => (cur === s ? null : s))}
          />

          <section className="card card--timeline">
            <ReplayControls
              mode={mode}
              playing={playing}
              speed={speed}
              cursor={cursor}
              times={series.times}
              incident={incident}
              onTogglePlay={togglePlay}
              onStep={(d) => {
                setPlaying(false);
                seek(cursor + d);
              }}
              onSeek={(i) => {
                setPlaying(false);
                seek(i);
              }}
              onSpeed={setSpeed}
              onRestart={restart}
            />

            <header className="card__header card__header--timeline">
              <h2>Service metrics</h2>
              <div className="card__tools">
                <div className="segmented" role="group" aria-label="Metric">
                  {(Object.keys(METRIC_LABELS) as Metric[]).map((m) => (
                    <button
                      key={m}
                      className={m === metric ? 'is-active' : ''}
                      onClick={() => setMetric(m)}
                    >
                      {METRIC_LABELS[m]}
                    </button>
                  ))}
                </div>
                <div className="segmented" role="group" aria-label="Time range">
                  {(Object.keys(SPANS) as SpanKey[]).map((k) => (
                    <button
                      key={k}
                      className={k === spanKey ? 'is-active' : ''}
                      onClick={() => setSpanKey(k)}
                    >
                      {k}
                    </button>
                  ))}
                </div>
              </div>
            </header>

            <Timeline
              series={series}
              order={order}
              metric={metric}
              viewStart={viewStart}
              viewEnd={Math.min(viewStart + span - 1, n - 1)}
              cursor={cursor}
              incident={incident}
              selected={selected}
              onSelect={setSelected}
              onScrub={(i) => {
                setPlaying(false);
                seek(i);
              }}
            />
          </section>
        </main>
      )}
    </div>
  );
}
