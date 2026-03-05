import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import { FadeIn, SlideUp, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE } from "../design-system";

export interface LineChartPoint {
  x: number;
  label?: string;
  y: number;
}

export interface LineChartProps {
  title: string;
  points: LineChartPoint[];
  yLabel?: string;
  accentColor?: string;
  bg?: "dark" | "light";
}

const CHART_MARGIN = { top: 60, right: 80, bottom: 80, left: 100 };
const CHART_W = 1920 - CHART_MARGIN.left - CHART_MARGIN.right;
const CHART_H = 600;

export const LineChart: React.FC<LineChartProps> = ({
  title,
  points,
  yLabel,
  accentColor = PALETTE.default_accent,
  bg = "dark",
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const foreground = fgColor(bg);
  const muted = PALETTE.muted;
  const bgStyle = proBgStyle(bg, accentColor);

  if (!points.length) return <AbsoluteFill style={{ backgroundColor: PALETTE.dark_bg }} />;

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;

  const drawProgress = interpolate(frame, [6, Math.min(40, durationInFrames - 8)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const toSvgX = (x: number) => CHART_MARGIN.left + ((x - minX) / rangeX) * CHART_W;
  const toSvgY = (y: number) => CHART_MARGIN.top + CHART_H - ((y - minY) / rangeY) * CHART_H;

  const pathPoints = points.map((p) => `${toSvgX(p.x)},${toSvgY(p.y)}`);
  const pathD = `M ${pathPoints.join(" L ")}`;

  let totalLen = 0;
  for (let i = 1; i < points.length; i++) {
    const dx = toSvgX(points[i].x) - toSvgX(points[i - 1].x);
    const dy = toSvgY(points[i].y) - toSvgY(points[i - 1].y);
    totalLen += Math.sqrt(dx * dx + dy * dy);
  }

  // Glow path under the main line
  const glowOpacity = interpolate(drawProgress, [0, 0.3], [0, 0.3], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <FadeIn durationFrames={10}>
          <h1
            style={{
              color: foreground,
              fontSize: TYPE_SCALE.title,
              fontWeight: 700,
              marginBottom: 20,
              textAlign: "center",
              fontFamily: FONTS.primary,
            }}
          >
            {title}
          </h1>
        </FadeIn>

        <SlideUp durationFrames={12} delay={4}>
          <svg
            width={1920}
            height={CHART_H + CHART_MARGIN.top + CHART_MARGIN.bottom}
            viewBox={`0 0 1920 ${CHART_H + CHART_MARGIN.top + CHART_MARGIN.bottom}`}
          >
            {/* Y axis */}
            <line
              x1={CHART_MARGIN.left}
              y1={CHART_MARGIN.top}
              x2={CHART_MARGIN.left}
              y2={CHART_MARGIN.top + CHART_H}
              stroke={muted}
              strokeWidth={1}
              opacity={0.2}
            />
            {/* X axis */}
            <line
              x1={CHART_MARGIN.left}
              y1={CHART_MARGIN.top + CHART_H}
              x2={CHART_MARGIN.left + CHART_W}
              y2={CHART_MARGIN.top + CHART_H}
              stroke={muted}
              strokeWidth={1}
              opacity={0.2}
            />

            {/* Y label */}
            {yLabel && (
              <text
                x={CHART_MARGIN.left - 60}
                y={CHART_MARGIN.top + CHART_H / 2}
                fill={muted}
                fontSize={TYPE_SCALE.caption}
                textAnchor="middle"
                transform={`rotate(-90, ${CHART_MARGIN.left - 60}, ${CHART_MARGIN.top + CHART_H / 2})`}
              >
                {yLabel}
              </text>
            )}

            {/* Glow line (wider, blurred) */}
            <path
              d={pathD}
              fill="none"
              stroke={accentColor}
              strokeWidth={16}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeDasharray={totalLen}
              strokeDashoffset={totalLen * (1 - drawProgress)}
              opacity={glowOpacity}
              filter="url(#lineGlow)"
            />

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

            {/* SVG filter for glow */}
            <defs>
              <filter id="lineGlow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="8" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            {/* Data points */}
            {points.map((p, i) => {
              const pointProgress = interpolate(
                drawProgress,
                [(i / points.length) * 0.8, Math.min(1, (i / points.length) * 0.8 + 0.15)],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              );
              return (
                <React.Fragment key={i}>
                  {/* Glow behind dot */}
                  <circle
                    cx={toSvgX(p.x)}
                    cy={toSvgY(p.y)}
                    r={14 * pointProgress}
                    fill={accentColor}
                    opacity={pointProgress * 0.2}
                  />
                  <circle
                    cx={toSvgX(p.x)}
                    cy={toSvgY(p.y)}
                    r={6 * pointProgress}
                    fill={accentColor}
                    opacity={pointProgress}
                  />
                </React.Fragment>
              );
            })}

            {/* X labels */}
            {points.map((p, i) => (
              p.label && (
                <text
                  key={`label-${i}`}
                  x={toSvgX(p.x)}
                  y={CHART_MARGIN.top + CHART_H + 40}
                  fill={muted}
                  fontSize={TYPE_SCALE.caption}
                  textAnchor="middle"
                >
                  {p.label}
                </text>
              )
            ))}
          </svg>
        </SlideUp>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
