"""Render the learned demo graph: uv run python scripts/render_causal_graph.py [--incident].

This checkout's generator lives in causeway.synthetic.generator rather than
tests/generate_synthetic_traces.py. Learn from 22 baseline hours, as the demo API
does; --incident colors a snapshot ten minutes into the planted incident.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
from datetime import datetime, timedelta
from pathlib import Path
import sys
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.lines import Line2D

from causeway.causal.graph_builder import CausalGraphBuilder
from causeway.pipeline import classify_health, slice_series, train_detector
from causeway.synthetic.generator import generate_incident, generate_normal_traffic
from causeway.timeseries.extractor import TimeSeriesExtractor


OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "causal_graph.png"
SERVICES = ["db-pool", "auth-service", "payment-service", "cart-service", "notification-service"]
COLORS = {"healthy": "#22c55e", "degraded": "#f59e0b", "critical": "#ef4444"}
BACKGROUND = "#0f172a"
TEXT = "#e2e8f0"


def learn_graph(incident: bool):
    start = datetime(2026, 1, 1)
    spans = generate_normal_traffic(
        SERVICES, hours=24, start=start, seed=42, dependency_chain=SERVICES
    )
    if incident:
        spans += generate_incident(
            SERVICES, start_time=start + timedelta(hours=22),
            root_cause_service=SERVICES[0], downstream_chain=SERVICES[1:], seed=7,
        )
    extractor = TimeSeriesExtractor()
    series = {s: extractor.extract(spans, s, start, window_hours=24) for s in SERVICES}
    baseline = {s: slice_series(ts, 22 * 60) for s, ts in series.items()}
    # Some statsmodels versions print every test; reserve stdout for the edge CSV.
    with contextlib.redirect_stdout(sys.stderr):
        graph = CausalGraphBuilder().build(baseline)
    health = dict.fromkeys(graph, "healthy")
    if incident:
        detector = train_detector(baseline)
        for service, ts in series.items():
            _, anomalous = detector.score_series(ts)
            health[service] = classify_health(anomalous)[22 * 60 + 10]
    return graph, health


def graph_layout(graph):
    if nx.is_directed_acyclic_graph(graph):
        layers = {i: sorted(nodes) for i, nodes in enumerate(nx.topological_generations(graph))}
        return nx.multipartite_layout(graph, subset_key=layers, align="vertical")
    return nx.spring_layout(graph, seed=42, k=1.4, iterations=200)


def render_graph(graph, health, output=OUTPUT, incident=False):
    fig, ax = plt.subplots(figsize=(12, 6.75), dpi=100, facecolor=BACKGROUND)
    fig.subplots_adjust(left=0.07, right=0.93, bottom=0.19, top=0.80)
    ax.set_facecolor(BACKGROUND)
    pos = graph_layout(graph)
    edges = list(graph.edges(data=True))
    node_size = 5600
    nx.draw_networkx_nodes(
        graph, pos, ax=ax, node_size=node_size,
        node_color=[COLORS[health[n]] for n in graph],
        edgecolors=TEXT, linewidths=1.5,
    )
    labels = {n: textwrap.fill(n, width=14, break_long_words=False) for n in graph}
    nx.draw_networkx_labels(graph, pos, labels=labels, ax=ax, font_size=10,
                            font_color=TEXT, font_weight="bold")
    max_f = max((d["f_statistic"] for _, _, d in edges), default=1.0)
    for source, target, data in edges:
        # Curve reciprocal and transitive edges away from nodes and other labels.
        radius = 0.22 if graph.has_edge(target, source) else 0.14
        connection = f"arc3,rad={radius}"
        nx.draw_networkx_edges(
            graph, pos, edgelist=[(source, target)], ax=ax,
            width=6 * data["f_statistic"] / max_f, edge_color="#94a3b8",
            arrows=True, arrowstyle="-|>", arrowsize=19, node_size=node_size,
            connectionstyle=connection,
        )
        nx.draw_networkx_edge_labels(
            graph, pos, edge_labels={(source, target): f'{data["lag_minutes"]} min'},
            ax=ax, font_color=TEXT, font_size=10, rotate=False, node_size=node_size,
            connectionstyle=connection,
            bbox={"facecolor": BACKGROUND, "edgecolor": "none", "pad": 3},
        )
    ax.margins(x=0.22, y=0.35)
    ax.set_axis_off()
    fig.suptitle("Causeway: learned causal graph", color=TEXT, fontsize=24, y=0.94)
    subtitle = "Health at incident +10 min" if incident else "Normal traffic baseline"
    fig.text(0.5, 0.855, subtitle, ha="center", color="#94a3b8", fontsize=11)
    if not edges:
        fig.text(0.5, 0.20, "No significant edges returned by the builder", ha="center", color=TEXT)
    handles = [Line2D([], [], marker="o", linestyle="none", color=c, label=s.title())
               for s, c in COLORS.items()]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.075),
               ncol=3, frameon=False, labelcolor=TEXT)
    fig.text(0.5, 0.035, "Synthetic data. Work in progress.", ha="center", color="#94a3b8")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=100, facecolor=BACKGROUND)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident", action="store_true", help="Show measured health at incident +10 min")
    args = parser.parse_args()
    graph, health = learn_graph(args.incident)
    writer = csv.writer(sys.stdout)
    writer.writerow(["source", "target", "lag", "F-stat", "p-value"])
    for source, target, data in graph.edges(data=True):
        writer.writerow([source, target, data["lag_minutes"], data["f_statistic"], data["p_value"]])
    render_graph(graph, health, incident=args.incident)
    print(f"Saved {OUTPUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
