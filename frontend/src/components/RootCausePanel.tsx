import { formatClock, formatMetricName, formatRelative } from '../format';
import type { Incident, RootCause } from '../types';

export type Phase = 'before' | 'active' | 'resolved';

interface Props {
  times: number[];
  cursor: number;
  incidents: Incident[];
  incidentIdx: number;
  onSelectIncident: (idx: number) => void;
  phase: Phase;
  report: RootCause | null;
  reportError: string | null;
  /** First non-healthy minute index of each service within the incident. */
  onsets: Record<string, number | null>;
  revealed: number;
  rootVisible: boolean;
  serviceCount: number;
  onSelectService: (service: string) => void;
}

export function RootCausePanel(props: Props) {
  const {
    times,
    cursor,
    incidents,
    incidentIdx,
    onSelectIncident,
    phase,
    report,
    reportError,
    onsets,
    revealed,
    rootVisible,
    serviceCount,
    onSelectService,
  } = props;
  const incident = incidents[incidentIdx] ?? null;
  const minutesIn = incident ? cursor - incident.start : 0;

  const identified = report?.status === 'ROOT_CAUSE_IDENTIFIED' && report.root_cause;
  const rootOnset = identified ? onsets[report!.root_cause!] : null;
  const lastOnset = Object.values(onsets).reduce<number | null>(
    (max, v) => (v !== null && v <= cursor && (max === null || v > max) ? v : max),
    null,
  );
  const affectedNow = Object.values(onsets).filter((v) => v !== null && v <= cursor).length;

  return (
    <aside className="panel">
      <header className="panel__header">
        <h2>Root cause analysis</h2>
      </header>

      <div className={`status status--${phase}`}>
        <span className="status__dot" />
        <div>
          {phase === 'before' && (
            <>
              <strong>All services nominal</strong>
              <span>Monitoring {serviceCount} services against the learned baseline</span>
            </>
          )}
          {phase === 'active' && incident && (
            <>
              <strong>Incident in progress</strong>
              <span>
                Detected {formatClock(times[incident.start])} · {formatRelative(minutesIn)} ·{' '}
                {affectedNow} of {serviceCount} services affected
              </span>
            </>
          )}
          {phase === 'resolved' && incident && (
            <>
              <strong>Incident resolved</strong>
              <span>
                {formatClock(times[incident.start])}–{formatClock(times[incident.end - 1])} ·{' '}
                {incident.end - incident.start} min · {incident.services.length} services
              </span>
            </>
          )}
        </div>
      </div>

      {phase !== 'before' && (
        <div className="panel__body">
          {reportError && <p className="panel__error">{reportError}</p>}
          {!report && !reportError && (
            <p className="panel__muted">
              <span className="spinner" /> Learning causal structure…
            </p>
          )}

          {report && !identified && rootVisible && (
            <div className="finding finding--neutral">
              <span className="finding__eyebrow">
                {report.status === 'NO_ANOMALY' ? 'No anomaly' : 'Independent failures'}
              </span>
              <p>{report.message ?? 'No causal path connects the anomalous services.'}</p>
            </div>
          )}

          {identified && !rootVisible && (
            <p className="panel__muted">
              <span className="spinner" /> Waiting for a sustained anomaly…
            </p>
          )}

          {identified && rootVisible && (
            <>
              <button
                className="finding"
                onClick={() => onSelectService(report!.root_cause!)}
                title="Highlight in graph"
              >
                <span className="finding__eyebrow">Root cause</span>
                <span className="finding__service">{report!.root_cause}</span>
                <span className="confidence">
                  <span className="confidence__bar">
                    <span style={{ width: `${Math.round((report!.confidence ?? 0) * 100)}%` }} />
                  </span>
                  <span className="confidence__value">
                    {Math.round((report!.confidence ?? 0) * 100)}% confidence
                  </span>
                </span>
                {rootOnset !== null && (
                  <span className="finding__meta">
                    first anomalous {formatClock(times[rootOnset])}
                  </span>
                )}
              </button>

              <h3 className="panel__subhead">Causal chain</h3>
              <ol className="chain">
                <li className="chain__node is-revealed">
                  <span className="chain__marker chain__marker--root" />
                  <span className="chain__service">{report!.root_cause}</span>
                  <span className="chain__when">
                    {rootOnset !== null ? formatClock(times[rootOnset]) : ''}
                  </span>
                </li>
                {report!.causal_chain.map((link, i) => {
                  const shown = i < revealed;
                  const s = onsets[link.source];
                  const t = onsets[link.target];
                  const observed = s !== null && t !== null ? t - s : null;
                  return (
                    <li
                      key={`${link.source}-${link.target}`}
                      className={`chain__node${shown ? ' is-revealed' : ''}`}
                    >
                      <span className="chain__edge">
                        <span className="chain__lag">learned lag {link.lag_minutes}m</span>
                        {shown && observed !== null && (
                          <span className="chain__observed">observed {observed}m</span>
                        )}
                        <span className="chain__via">
                          {link.metrics.map(formatMetricName).join(' · ')}
                        </span>
                      </span>
                      <span className="chain__marker" />
                      <button
                        className="chain__service"
                        onClick={() => onSelectService(link.target)}
                      >
                        {link.target}
                      </button>
                      <span className="chain__when">
                        {shown && t !== null ? formatClock(times[t]) : 'pending'}
                      </span>
                    </li>
                  );
                })}
              </ol>

              <dl className="stats">
                <div>
                  <dt>Learned propagation</dt>
                  <dd>{report!.total_propagation_minutes} min</dd>
                </div>
                <div>
                  <dt>Observed spread</dt>
                  <dd>
                    {rootOnset !== null && lastOnset !== null
                      ? `${lastOnset - rootOnset} min`
                      : '—'}
                  </dd>
                </div>
                <div>
                  <dt>Hops</dt>
                  <dd>
                    {Math.min(revealed, report!.causal_chain.length)}/{report!.causal_chain.length}
                  </dd>
                </div>
              </dl>
            </>
          )}
        </div>
      )}

      {incidents.length > 0 && (
        <footer className="panel__footer">
          <h3 className="panel__subhead">Detected incidents</h3>
          <div className="incidents">
            {incidents.map((inc, i) => (
              <button
                key={inc.start}
                className={`incident-chip${i === incidentIdx ? ' is-active' : ''}`}
                onClick={() => onSelectIncident(i)}
              >
                <strong>{formatClock(times[inc.start])}</strong>
                <span>
                  {inc.services.length} svc · {inc.end - inc.start}m
                </span>
              </button>
            ))}
          </div>
        </footer>
      )}
    </aside>
  );
}
