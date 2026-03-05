/**
 * KpiChart — Combined big counter number + rising line chart.
 *
 * Renders a giant ghost number behind, a live CountUpNumber in a tooltip,
 * and an animated SVG line chart rising from bottom-left.
 * Designed for portrait (1080x1920).
 */
import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from "remotion";
import {
  FadeIn,
  ScaleSpring,
  CountUpNumber,
  HeroStack,
  ProSceneWrapper,
} from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE } from "../design-system";

export interface KpiChartPoint {
  x: number;
  label?: string;
  y: number;
}

export interface KpiChartProps {
  label: string;
  value: number;
  prefix?: string;
  suffix?: string;
  points: KpiChartPoint[];
  accentColor?: string;
  bg?: "dark" | "light";
}

// Chart dimensions for portrait canvas (1080x1920)
const CHART_W = 900;
const CHART_H = 500;
const CHART_LEFT = 90;
const CHART_TOP = 1100;

export const KpiChart: React.FC<KpiChartProps> = ({
  label,
  value,
  prefix = "",
  suffix = "",
  points,
  accentColor = PALETTE.default_accent,
  bg = "dark",
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const foreground = fgColor(bg);
  const bgStyle = proBgStyle(bg, accentColor);

  const ghostText = prefix + value.toLocaleString() + suffix;

  // Chart data mapping
  if (!points.length) {
    return (
      <AbsoluteFill>
        <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
          <ScaleSpring delay={5}>
            <HeroStack
              label={label}
              hero={
                <CountUpNumber
                  value={value}
                  prefix={prefix}
                  suffix={suffix}
                  durationFrames={50}
                  delay={8}
                  style={{ color: foreground, fontSize: TYPE_SCALE.hero, fontWeight: 700, fontFamily: FONTS.display }}
                />
              }
              ghost={ghostText}
              color={foreground}
              accentColor={accentColor}
              anchor="center"
            />
          </ScaleSpring>
        </ProSceneWrapper>
      </AbsoluteFill>
    );
  }

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;

  // Line draw progress: starts at frame 10, completes by frame 50
  const drawProgress = interpolate(
    frame,
    [10, Math.min(50, durationInFrames - 10)],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
  );

  const toSvgX = (x: number) => ((x - minX) / rangeX) * CHART_W;
  const toSvgY = (y: number) => CHART_H - ((y - minY) / rangeY) * CHART_H;

  const pathPoints = points.map((p) => `${toSvgX(p.x)},${toSvgY(p.y)}`);
  const pathD = `M ${pathPoints.join(" L ")}`;

  let totalLen = 0;
  for (let i = 1; i < points.length; i++) {
    const dx = toSvgX(points[i].x) - toSvgX(points[i - 1].x);
    const dy = toSvgY(points[i].y) - toSvgY(points[i - 1].y);
    totalLen += Math.sqrt(dx * dx + dy * dy);
  }

  // Find the current tip position along the drawn path
  const lastPoint = points[points.length - 1];
  const tipX = toSvgX(lastPoint.x);
  const tipY = toSvgY(lastPoint.y);

  // Tooltip appears when line is mostly drawn
  const tooltipOpacity = interpolate(drawProgress, [0.6, 0.85], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        {/* Giant ghost number — centered in upper portion */}
        <div
          style={{
            position: "absolute",
            top: 200,
            left: 0,
            right: 0,
            display: "flex",
            justifyContent: "center",
            zIndex: 0,
            pointerEvents: "none",
          }}
        >
          <FadeIn durationFrames={20} delay={3}>
            <span
              style={{
                fontFamily: FONTS.display,
                fontSize: 280,
                fontWeight: 700,
                color: foreground,
                opacity: 0.07,
                filter: "blur(2px)",
                letterSpacing: "-0.03em",
                lineHeight: 0.85,
                whiteSpace: "nowrap",
              }}
            >
              {ghostText}
            </span>
          </FadeIn>
        </div>

        {/* Tooltip badge — positioned near the chart tip */}
        <div
          style={{
            position: "absolute",
            left: CHART_LEFT + tipX * drawProgress - 70,
            top: CHART_TOP + tipY - 100,
            zIndex: 10,
            opacity: tooltipOpacity,
          }}
        >
          <div
            style={{
              backgroundColor: "rgba(30, 30, 40, 0.9)",
              borderRadius: 12,
              padding: "14px 22px",
              backdropFilter: "blur(8px)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
          >
            <div
              style={{
                fontFamily: FONTS.ui,
                fontSize: 16,
                fontWeight: 600,
                color: PALETTE.muted,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                marginBottom: 4,
              }}
            >
              {label}
            </div>
            <CountUpNumber
              value={value}
              prefix={prefix}
              suffix={suffix}
              durationFrames={50}
              delay={8}
              style={{
                fontFamily: FONTS.display,
                fontSize: 32,
                fontWeight: 700,
                color: foreground,
              }}
            />
          </div>
        </div>

        {/* SVG line chart — lower portion */}
        <div
          style={{
            position: "absolute",
            left: CHART_LEFT,
            top: CHART_TOP,
            zIndex: 5,
          }}
        >
          <svg width={CHART_W} height={CHART_H} viewBox={`0 0 ${CHART_W} ${CHART_H}`}>
            {/* Glow under the line */}
            <defs>
              <linearGradient id="lineGlow" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={accentColor} stopOpacity={0.3} />
                <stop offset="100%" stopColor={accentColor} stopOpacity={0} />
              </linearGradient>
            </defs>

            {/* Area fill under the line */}
            {drawProgress > 0.05 && (
              <path
                d={`${pathD} L ${toSvgX(lastPoint.x)},${CHART_H} L ${toSvgX(points[0].x)},${CHART_H} Z`}
                fill="url(#lineGlow)"
                opacity={drawProgress * 0.5}
              />
            )}

            {/* Main data line */}
            <path
              d={pathD}
              fill="none"
              stroke={accentColor}
              strokeWidth={4}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeDasharray={totalLen}
              strokeDashoffset={totalLen * (1 - drawProgress)}
            />

            {/* Dot at the tip */}
            {drawProgress > 0.1 && (
              <>
                {/* Glow ring */}
                <circle
                  cx={tipX}
                  cy={tipY}
                  r={12 * Math.min(drawProgress * 2, 1)}
                  fill="none"
                  stroke={accentColor}
                  strokeWidth={2}
                  opacity={0.4}
                />
                {/* Solid dot */}
                <circle
                  cx={tipX}
                  cy={tipY}
                  r={7 * Math.min(drawProgress * 2, 1)}
                  fill={accentColor}
                />
              </>
            )}

            {/* X-axis labels */}
            {points.map((p, i) => {
              const pointOpacity = interpolate(
                drawProgress,
                [(i / points.length) * 0.7, Math.min(1, (i / points.length) * 0.7 + 0.2)],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              );
              return p.label ? (
                <text
                  key={`label-${i}`}
                  x={toSvgX(p.x)}
                  y={CHART_H - 10}
                  fill={PALETTE.muted}
                  fontSize={18}
                  fontFamily={FONTS.ui}
                  textAnchor="middle"
                  opacity={pointOpacity}
                >
                  {p.label}
                </text>
              ) : null;
            })}
          </svg>
        </div>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
