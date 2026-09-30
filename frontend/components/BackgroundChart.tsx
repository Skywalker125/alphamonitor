"use client";

import { useId, useMemo } from "react";
import type { ChartPoints } from "@/lib/api";

const W = 100;
const H = 40;
const PAD = 4; // vertical padding so peaks aren't clipped

/** Catmull-Rom spline through the points, as cubic Bezier segments (smooth like the reference). */
function smoothPath(pts: [number, number][]) {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return d;
}

/** Faint price line behind a token row. Purely decorative, never catches clicks. */
export default function BackgroundChart({ points }: { points: ChartPoints }) {
  const id = useId().replace(/:/g, "");
  const geo = useMemo(() => {
    if (points.length < 2) return null;
    const t0 = points[0][0];
    const t1 = points[points.length - 1][0];
    const closes = points.map((p) => p[1]);
    const lo = Math.min(...closes);
    const hi = Math.max(...closes);
    const span = hi - lo || hi || 1;
    const xy = points.map(([t, c]) => [
      t1 > t0 ? ((t - t0) / (t1 - t0)) * W : 0,
      PAD + (1 - (c - lo) / span) * (H - 2 * PAD),
    ]) as [number, number][];
    const line = smoothPath(xy);
    const last = xy[xy.length - 1];
    return {
      line,
      area: `${line} L${W},${H} L0,${H} Z`,
      last,
      up: closes[closes.length - 1] >= closes[0],
    };
  }, [points]);

  if (!geo) return null;
  const color = geo.up ? "var(--chart-up)" : "var(--chart-down)";
  return (
    <svg className="row-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={geo.area} fill={`url(#g${id})`} />
      <path d={geo.line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}
