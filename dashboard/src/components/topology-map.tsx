import { useMemo, useState } from "react";

interface Edge {
  caller: string;
  callee: string;
  calls_per_request?: number;
}

interface NodePosition {
  service: string;
  x: number;
  y: number;
}

function layout(services: string[], edges: Edge[]): NodePosition[] {
  const depth = new Map(services.map((service) => [service, 0]));
  for (let pass = 0; pass < services.length; pass += 1) {
    for (const edge of edges) {
      depth.set(
        edge.callee,
        Math.max(depth.get(edge.callee) ?? 0, (depth.get(edge.caller) ?? 0) + 1),
      );
    }
  }
  const layers = new Map<number, string[]>();
  for (const service of services) {
    const level = Math.min(depth.get(service) ?? 0, 3);
    layers.set(level, [...(layers.get(level) ?? []), service]);
  }
  return [...layers.entries()].flatMap(([level, layer]) =>
    layer.map((service, index) => ({
      service,
      x: 82 + level * 170,
      y: 48 + index * (164 / Math.max(layer.length - 1, 1)),
    })),
  );
}

export function TopologyMap({
  services,
  edges,
  origin,
  attackTarget,
  load,
  onSelect,
}: {
  services: string[];
  edges: Edge[];
  origin: string;
  attackTarget: string;
  load: number;
  onSelect: (service: string) => void;
}) {
  const [selected, setSelected] = useState(origin);
  const positions = useMemo(() => layout(services, edges), [edges, services]);
  const byService = new Map(positions.map((node) => [node.service, node]));

  return (
    <div>
      <svg
        viewBox="0 0 650 260"
        className="mt-4 w-full overflow-visible"
        role="img"
        aria-label={`Service dependency topology. Root cause: ${origin}.`}
      >
        <defs>
          <marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
            <path d="M0,0 L7,3.5 L0,7 Z" fill="var(--muted)" />
          </marker>
          <marker
            id="arrow-origin"
            markerWidth="7"
            markerHeight="7"
            refX="6"
            refY="3.5"
            orient="auto"
          >
            <path d="M0,0 L7,3.5 L0,7 Z" fill="var(--warning)" />
          </marker>
        </defs>
        {edges.map((edge) => {
          const from = byService.get(edge.caller);
          const to = byService.get(edge.callee);
          if (!from || !to) return null;
          const traced = edge.caller === origin || edge.callee === origin;
          const edgeLoad = load * (edge.calls_per_request ?? 0.1);
          return (
            <line
              key={`${edge.caller}-${edge.callee}`}
              x1={from.x + 62}
              y1={from.y}
              x2={to.x - 62}
              y2={to.y}
              stroke={
                traced ? "var(--warning)" : edgeLoad > 1 ? "var(--accent)" : "var(--line)"
              }
              strokeWidth={traced ? 3 : Math.min(4, 1 + edgeLoad)}
              strokeDasharray={traced ? "7 5" : undefined}
              markerEnd={traced ? "url(#arrow-origin)" : "url(#arrow)"}
              className={traced ? "topology-trace" : undefined}
            />
          );
        })}
        {positions.map((node) => {
          const isOrigin = node.service === origin;
          const isTarget = node.service === attackTarget;
          const isSelected = node.service === selected;
          return (
            <g
              key={node.service}
              role="button"
              tabIndex={0}
              aria-label={`${node.service}${isOrigin ? ", root cause" : ""}`}
              onClick={() => {
                setSelected(node.service);
                onSelect(node.service);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  setSelected(node.service);
                  onSelect(node.service);
                }
              }}
              className="cursor-pointer outline-none"
            >
              {isOrigin && (
                <circle
                  cx={node.x}
                  cy={node.y}
                  r="43"
                  fill="none"
                  stroke="var(--warning)"
                  strokeWidth="2"
                  className="topology-pulse"
                />
              )}
              <rect
                x={node.x - 62}
                y={node.y - 24}
                width="124"
                height="48"
                rx="10"
                fill={
                  isOrigin
                    ? "color-mix(in srgb, var(--warning) 13%, var(--raised))"
                    : isTarget
                      ? "color-mix(in srgb, var(--danger) 10%, var(--raised))"
                      : "var(--sidebar)"
                }
                stroke={
                  isOrigin
                    ? "var(--warning)"
                    : isTarget
                      ? "var(--danger)"
                      : isSelected
                        ? "var(--accent)"
                        : "var(--line)"
                }
                strokeWidth={isOrigin || isTarget || isSelected ? 2 : 1}
              />
              <text
                x={node.x}
                y={node.y - 2}
                textAnchor="middle"
                fill="var(--ink)"
                fontSize="12"
                fontWeight="700"
              >
                {node.service}
              </text>
              <text
                x={node.x}
                y={node.y + 13}
                textAnchor="middle"
                fill={isOrigin ? "var(--warning)" : isTarget ? "var(--danger)" : "var(--muted)"}
                fontSize="8"
                fontWeight="700"
                letterSpacing="1"
              >
                {isOrigin ? "ROOT CAUSE" : isTarget ? "ATTACK TARGET" : "HEALTHY"}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="flex items-center justify-between rounded-md border border-line bg-sidebar px-3 py-2 text-xs">
        <span className="text-muted">Selected service</span>
        <span className="font-bold text-ink">{selected}</span>
        <span className="tnum text-muted">live load {load.toFixed(1)}×</span>
      </div>
    </div>
  );
}
