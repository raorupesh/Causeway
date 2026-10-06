import * as d3 from 'd3';
import { useMemo, useRef } from 'react';
import { formatClock, formatMetric } from '../format';
import type { Health, Incident, Metric, Series } from '../types';
import { useSize } from '../useSize';

interface Props {
  series: Series;
  order: string[];
  metric: Metric;
  viewStart: number;
  viewEnd: number; // inclusive index
  cursor: number;
  incident: Incident | null;
  selected: string | null;
  onSelect: (service: string | null) => void;
  onScrub: (index: number) => void;
}

const ROW_H = 46;
const STRIP_H = 6;
const AXIS_H = 22;
const TOP = 18;

export function Timeline(props: Props) {
  const {
    series,
    order,
    metric,
    viewStart,
    viewEnd,
    cursor,
    incident,
    selected,
    onSelect,
    onScrub,
  } = props;
  const [ref, size] = useSize<HTMLDivElement>();
  const scrubbing = useRef(false);
  const LABEL_W = size.width < 520 ? 124 : 176;

  const plotW = Math.max(size.width - LABEL_W - 12, 50);
  const height = TOP + order.length * ROW_H + AXIS_H;

  const x = useMemo(
    () => d3.scaleLinear().domain([viewStart, viewEnd]).range([0, plotW]),
    [viewStart, viewEnd, plotW],
  );
  const ticks = useMemo(() => {
    const t = d3
      .scaleTime()
      .domain([series.times[viewStart], series.times[viewEnd]])
      .ticks(Math.max(2, Math.floor(plotW / 110)));
    const t0 = series.times[viewStart];
    return t.map((d) => ({ ms: d.getTime(), x: x(viewStart + (d.getTime() - t0) / 60000) }));
  }, [series.times, viewStart, viewEnd, plotW, x]);

  const step = plotW / Math.max(viewEnd - viewStart, 1);

  const rows = useMemo(
    () =>
      order.map((service) => {
        const s = series.services[service];
        const values = s[metric].slice(viewStart, viewEnd + 1);
        const [lo, hi] = d3.extent(values) as [number, number];
        const y = d3
          .scaleLinear()
          .domain([Math.min(lo, 0), hi === lo ? hi + 1 : hi])
          .range([ROW_H - STRIP_H - 6, 6]);
        const line = d3
          .line<number>()
          .x((_, i) => x(viewStart + i))
          .y((v) => y(v))
          .curve(d3.curveMonotoneX);
        const area = d3
          .area<number>()
          .x((_, i) => x(viewStart + i))
          .y0(y(Math.min(lo, 0)))
          .y1((v) => y(v))
          .curve(d3.curveMonotoneX);
        return {
          service,
          line: line(values) ?? '',
          area: area(values) ?? '',
          runs: healthRuns(s.health, viewStart, viewEnd),
        };
      }),
    [order, series, metric, viewStart, viewEnd, x],
  );

  const indexAt = (clientX: number, el: Element) => {
    const rect = el.getBoundingClientRect();
    const px = clientX - rect.left;
    return Math.round(Math.max(viewStart, Math.min(viewEnd, x.invert(px))));
  };

  const cursorX = cursor >= viewStart && cursor <= viewEnd ? x(cursor) : null;

  return (
    <div className="timeline" ref={ref}>
      {size.width > 0 && (
        <svg width={size.width} height={height}>
          <g transform={`translate(${LABEL_W},0)`}>
            {incident && incident.end > viewStart && incident.start <= viewEnd && (
              <g className="timeline__incident">
                <rect
                  x={x(Math.max(incident.start, viewStart))}
                  y={TOP - 4}
                  width={Math.max(
                    x(Math.min(incident.end, viewEnd)) - x(Math.max(incident.start, viewStart)),
                    2,
                  )}
                  height={order.length * ROW_H + 4}
                />
                {incident.start >= viewStart && (
                  <text x={x(incident.start) + 4} y={TOP - 6}>
                    incident
                  </text>
                )}
              </g>
            )}

            {ticks.map((t) => (
              <g key={t.ms} transform={`translate(${t.x},0)`} className="timeline__tick">
                <line y1={TOP} y2={TOP + order.length * ROW_H} />
                <text y={TOP + order.length * ROW_H + 15}>{formatClock(t.ms)}</text>
              </g>
            ))}
          </g>

          {rows.map((row, i) => {
            const s = series.services[row.service];
            const value = s[metric][cursor];
            const h = s.health[cursor];
            return (
              <g
                key={row.service}
                transform={`translate(0,${TOP + i * ROW_H})`}
                className={`timeline__row${selected === row.service ? ' is-selected' : ''}${selected && selected !== row.service ? ' is-dimmed' : ''}`}
              >
                <rect className="timeline__row-bg" width={size.width} height={ROW_H} />
                <g
                  className="timeline__label"
                  onClick={() => onSelect(selected === row.service ? null : row.service)}
                >
                  <rect width={LABEL_W - 8} height={ROW_H} fill="transparent" />
                  <circle cx={14} cy={ROW_H / 2 - 7} r={5} className={`fill--${h}`} />
                  <text x={26} y={ROW_H / 2 - 3} className="timeline__name">
                    {row.service}
                  </text>
                  <text x={26} y={ROW_H / 2 + 13} className={`timeline__value text--${h}`}>
                    {formatMetric(metric, value)}
                  </text>
                </g>
                <g transform={`translate(${LABEL_W},0)`}>
                  <path d={row.area} className="timeline__area" />
                  <path d={row.line} className="timeline__line" />
                  {row.runs.map((r) => (
                    <rect
                      key={r.start}
                      x={x(r.start) - step / 2}
                      y={ROW_H - STRIP_H - 2}
                      width={Math.max((r.end - r.start + 1) * step, 1)}
                      height={STRIP_H}
                      className={`fill--${r.health}`}
                    />
                  ))}
                </g>
              </g>
            );
          })}

          <g transform={`translate(${LABEL_W},0)`}>
            {cursorX !== null && (
              <g className="timeline__cursor" transform={`translate(${cursorX},0)`}>
                <line y1={TOP - 6} y2={TOP + order.length * ROW_H} />
                <path d="M-5,4 L5,4 L0,11 z" />
              </g>
            )}
            <rect
              className="timeline__scrub"
              y={0}
              width={plotW}
              height={TOP + order.length * ROW_H}
              onPointerDown={(e) => {
                scrubbing.current = true;
                e.currentTarget.setPointerCapture(e.pointerId);
                onScrub(indexAt(e.clientX, e.currentTarget));
              }}
              onPointerMove={(e) => {
                if (scrubbing.current) onScrub(indexAt(e.clientX, e.currentTarget));
              }}
              onPointerUp={() => (scrubbing.current = false)}
              onPointerCancel={() => (scrubbing.current = false)}
            />
          </g>
        </svg>
      )}
    </div>
  );
}

/** Collapse a per-minute health array into runs of equal status, so a strip
 *  is a handful of rects rather than one per minute. */
function healthRuns(health: Health[], from: number, to: number) {
  const runs: { start: number; end: number; health: Health }[] = [];
  for (let i = from; i <= to; i++) {
    const h = health[i];
    const last = runs[runs.length - 1];
    if (last && last.health === h && last.end === i - 1) last.end = i;
    else runs.push({ start: i, end: i, health: h });
  }
  return runs;
}
