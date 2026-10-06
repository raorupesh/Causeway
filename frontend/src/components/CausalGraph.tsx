import * as d3 from 'd3';
import { useEffect, useMemo, useRef, useState } from 'react';
import { formatMetricName } from '../format';
import type { ChainLink, GraphEdge, Health } from '../types';
import { useSize } from '../useSize';

interface Props {
  nodes: string[];
  edges: GraphEdge[];
  /** Service order used to lay the graph out top-to-bottom (cascade order). */
  order: string[];
  health: Record<string, Health>;
  chain: ChainLink[];
  /** How many links of `chain` have propagated so far at the cursor. */
  revealed: number;
  rootCause: string | null;
  selected: string | null;
  onSelect: (service: string | null) => void;
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
}

const R = 24;

export function CausalGraph(props: Props) {
  const { nodes, edges, order, health, chain, revealed, rootCause, selected, onSelect } = props;
  const [containerRef, size] = useSize<HTMLDivElement>();
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const simRef = useRef<d3.Simulation<SimNode, undefined> | null>(null);
  const simNodesRef = useRef<Map<string, SimNode>>(new Map());
  const dragRef = useRef<{ x: number; y: number; moved: boolean } | null>(null);

  // (Re)build the force simulation when the graph or the available space changes.
  useEffect(() => {
    const { width, height } = size;
    if (!width || !height || nodes.length === 0) return;

    const previous = simNodesRef.current;
    const simNodes: SimNode[] = nodes.map((id, i) => {
      const old = previous.get(id);
      return old
        ? { id, x: old.x, y: old.y }
        : { id, x: width / 2 + Math.cos(i * 2.4) * 80, y: height / 2 + Math.sin(i * 2.4) * 80 };
    });
    simNodesRef.current = new Map(simNodes.map((n) => [n.id, n]));

    const pad = R * 2.2;
    const rank = (id: string) => {
      const i = order.indexOf(id);
      return i < 0 ? (order.length - 1) / 2 : i;
    };
    const steps = Math.max(order.length - 1, 1);
    const rankY = (id: string) => pad + (rank(id) / steps) * (height - pad * 2);
    // Zig-zag successive ranks left/right so chain edges don't overlap.
    const rankX = (id: string) =>
      width / 2 + (rank(id) % 2 === 0 ? -1 : 1) * Math.min(width * 0.2, 220);

    const links = edges.map((e) => ({ source: e.source, target: e.target }));
    const sim = d3
      .forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, { source: string; target: string }>(links)
          .id((d) => d.id)
          .distance(Math.min(width, height) * 0.32)
          .strength(0.05),
      )
      .force('charge', d3.forceManyBody().strength(-500))
      .force('collide', d3.forceCollide(R * 2.2))
      .force('y', d3.forceY<SimNode>((d) => rankY(d.id)).strength(0.5))
      .force('x', d3.forceX<SimNode>((d) => rankX(d.id)).strength(0.25))
      .stop();

    const clamp = () => {
      for (const n of simNodes) {
        n.x = Math.max(pad, Math.min(width - pad, n.x ?? 0));
        n.y = Math.max(pad * 0.7, Math.min(height - pad * 0.7, n.y ?? 0));
      }
    };
    const publish = () => {
      clamp();
      setPositions(Object.fromEntries(simNodes.map((n) => [n.id, { x: n.x!, y: n.y! }])));
    };

    // Settle the layout synchronously so the first paint is already stable;
    // the animated simulation only runs while a node is being dragged.
    for (let i = 0; i < 300; i++) {
      sim.tick();
      clamp();
    }
    publish();
    sim.alpha(0).on('tick', publish);

    simRef.current = sim;
    return () => {
      sim.stop();
    };
  }, [nodes, edges, order, size]);

  const widthScale = useMemo(() => {
    const extent = d3.extent(edges, (e) => e.f_statistic) as [number, number];
    return d3
      .scaleSqrt()
      .domain(extent[0] === undefined ? [0, 1] : extent)
      .range([1.25, 5]);
  }, [edges]);

  const chainKeys = useMemo(() => {
    const all = new Map<string, number>();
    chain.forEach((l, i) => all.set(`${l.source}→${l.target}`, i));
    return all;
  }, [chain]);

  const dragStart = (id: string, e: React.PointerEvent) => {
    const node = simNodesRef.current.get(id);
    if (!node) return;
    (e.target as Element).setPointerCapture(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, moved: false };
    node.fx = node.x;
    node.fy = node.y;
    simRef.current?.alphaTarget(0.3).restart();
  };
  const dragMove = (id: string, e: React.PointerEvent<SVGGElement>) => {
    const node = simNodesRef.current.get(id);
    const drag = dragRef.current;
    if (!node || node.fx == null || !drag) return;
    if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 3) drag.moved = true;
    const svg = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    node.fx = e.clientX - svg.left;
    node.fy = e.clientY - svg.top;
  };
  const dragEnd = (id: string) => {
    const node = simNodesRef.current.get(id);
    if (!node) return;
    node.fx = null;
    node.fy = null;
    simRef.current?.alphaTarget(0);
  };

  const hovered = hoverEdge ? edges.find((e) => `${e.source}→${e.target}` === hoverEdge) : null;

  return (
    <div className="graph">
      <div className="graph__canvas" ref={containerRef}>
        {size.width > 0 && (
          <svg width={size.width} height={size.height} onClick={() => onSelect(null)}>
            <defs>
              {(['edge', 'chain', 'pending'] as const).map((kind) => (
                <marker
                  key={kind}
                  id={`arrow-${kind}`}
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerUnits="userSpaceOnUse"
                  markerWidth={kind === 'edge' ? 9 : 12}
                  markerHeight={kind === 'edge' ? 9 : 12}
                  orient="auto-start-reverse"
                >
                  <path d="M0,0 L10,5 L0,10 z" className={`arrowhead arrowhead--${kind}`} />
                </marker>
              ))}
            </defs>

            <g>
              {edges.map((e) => {
                const s = positions[e.source];
                const t = positions[e.target];
                if (!s || !t) return null;
                const key = `${e.source}→${e.target}`;
                const chainIdx = chainKeys.get(key);
                const kind =
                  chainIdx === undefined ? 'edge' : chainIdx < revealed ? 'chain' : 'pending';
                const geom = curve(s, t);
                const dimmed = selected !== null && e.source !== selected && e.target !== selected;
                return (
                  <g
                    key={key}
                    className={`edge edge--${kind}${dimmed ? ' is-dimmed' : ''}${hoverEdge === key ? ' is-hover' : ''}`}
                    onPointerEnter={() => setHoverEdge(key)}
                    onPointerLeave={() => setHoverEdge(null)}
                  >
                    <path d={geom.d} className="edge__hit" />
                    <path
                      d={geom.d}
                      className="edge__line"
                      strokeWidth={
                        kind === 'edge' ? widthScale(e.f_statistic) : widthScale(e.f_statistic) + 1
                      }
                      markerEnd={`url(#arrow-${kind})`}
                    />
                    {(kind !== 'edge' || hoverEdge === key) && (
                      <text x={geom.mid.x} y={geom.mid.y} className="edge__label" dy="0.35em">
                        {e.lag_minutes}m
                      </text>
                    )}
                  </g>
                );
              })}
            </g>

            <g>
              {nodes.map((id) => {
                const p = positions[id];
                if (!p) return null;
                const h = health[id] ?? 'healthy';
                const isRoot = id === rootCause;
                const dimmed =
                  selected !== null &&
                  id !== selected &&
                  !edges.some(
                    (e) =>
                      (e.source === selected && e.target === id) ||
                      (e.target === selected && e.source === id),
                  );
                return (
                  <g
                    key={id}
                    className={`node node--${h}${isRoot ? ' is-root' : ''}${selected === id ? ' is-selected' : ''}${dimmed ? ' is-dimmed' : ''}`}
                    transform={`translate(${p.x},${p.y})`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (dragRef.current?.moved) return;
                      onSelect(selected === id ? null : id);
                    }}
                    onPointerDown={(e) => dragStart(id, e)}
                    onPointerMove={(e) => dragMove(id, e)}
                    onPointerUp={() => dragEnd(id)}
                    role="button"
                    aria-label={`${id}: ${h}`}
                  >
                    {isRoot && <circle r={R + 10} className="node__pulse" />}
                    <circle r={R + 4} className="node__halo" />
                    <circle r={R} className="node__body" />
                    <text className="node__glyph" dy="0.35em">
                      {initials(id)}
                    </text>
                    <text className="node__label" y={R + 18}>
                      {id}
                    </text>
                    {isRoot && (
                      <text className="node__tag" y={-R - 12}>
                        ROOT CAUSE
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>
        )}

        {hovered && (
          <div className="graph__tooltip">
            <strong>
              {hovered.source} → {hovered.target}
            </strong>
            <span>
              lag {hovered.lag_minutes} min · F = {hovered.f_statistic.toFixed(1)} · p ={' '}
              {hovered.p_value.toExponential(1)}
            </span>
            <span>via {hovered.metrics.map(formatMetricName).join(', ')}</span>
          </div>
        )}
      </div>

      <div className="graph__legend">
        <span>
          <i className="dot dot--healthy" /> healthy
        </span>
        <span>
          <i className="dot dot--degraded" /> degraded
        </span>
        <span>
          <i className="dot dot--critical" /> critical
        </span>
        <span className="graph__legend-note">edge width = Granger F-statistic · label = lag</span>
      </div>
    </div>
  );
}

function initials(service: string): string {
  return service
    .replace(/-service$/, '')
    .split('-')
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('')
    .slice(0, 2);
}

/** Curved edge between two node centers, trimmed to the node radius. Opposite
 *  directions bow to opposite sides, so A→B and B→A never overlap. */
function curve(s: { x: number; y: number }, t: { x: number; y: number }) {
  const dx = t.x - s.x;
  const dy = t.y - s.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const bow = Math.min(len * 0.18, 40);
  const cx = (s.x + t.x) / 2 - uy * bow;
  const cy = (s.y + t.y) / 2 + ux * bow;

  // Trim along the direction from each end toward the control point.
  const trim = (px: number, py: number, by: number) => {
    const vx = cx - px;
    const vy = cy - py;
    const vl = Math.hypot(vx, vy) || 1;
    return { x: px + (vx / vl) * by, y: py + (vy / vl) * by };
  };
  const a = trim(s.x, s.y, R + 5);
  const b = trim(t.x, t.y, R + 7);
  return {
    d: `M${a.x},${a.y} Q${cx},${cy} ${b.x},${b.y}`,
    mid: { x: 0.25 * a.x + 0.5 * cx + 0.25 * b.x, y: 0.25 * a.y + 0.5 * cy + 0.25 * b.y },
  };
}
