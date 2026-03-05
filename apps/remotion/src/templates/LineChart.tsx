import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import { FadeIn, SlideUp, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor } from "../design-system";

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

// Portrait-optimized chart dimensions (1080x1920 canvas)
const CHART_MARGIN = { top: 40, right: 60, bottom: 60, left: 80 };
const CHART_W = 1080 - CHART_MARGIN.left - CHART_MARGIN.right;
const CHART_H = 700;

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

  const drawProgress = interpolate(frame, [8, Math.min(50, durationInFrames - 10)], [0, 1], {
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

  const svgW = 1080;
  const svgH = CHART_H + CHART_MARGIN.top + CHART_MARGIN.bottom;

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <FadeIn durationFrames={12}>
          <h1
            style={{
              color: foreground,
              fontSize: 44,
              fontWeight: 700,
              fontFamily: FONTS.display,
              marginBottom: 24,
              textAlign: "center",
            }}
          >
            {title}
          </h1>
        </FadeIn>

        <SlideUp durationFrames={15} delay={5}>
          <svg
            width={svgW}
            height={svgH}
            viewBox={`0 0 ${svgW} ${svgH}`}
          >
            {/* Y axis */}
            <line
              x1={CHART_MARGIN.left}
              y1={CHART_MARGIN.top}
              x2={CHART_MARGIN.left}
              y2={CHART_MARGIN.top + CHART_H}
              stroke={muted}
              strokeWidth={1}
              opacity={0.3}
            />
            {/* X axis */}
            <line
              x1={CHART_MARGIN.left}
              y1={CHART_MARGIN.top + CHART_H}
              x2={CHART_MARGIN.left + CHART_W}
              y2={CHART_MARGIN.top + CHART_H}
              stroke={muted}
              strokeWidth={1}
              opacity={0.3}
            />

            {/* Y label */}
            {yLabel && (
              <text
                x={CHART_MARGIN.left - 50}
                y={CHART_MARGIN.top + CHART_H / 2}
                fill={muted}
                fontSize={20}
                fontFamily={FONTS.ui}
                textAnchor="middle"
                transform={`rotate(-90, ${CHART_MARGIN.left - 50}, ${CHART_MARGIN.top + CHART_H / 2})`}
              >
                {yLabel}
              </text>
            )}

            {/* Area fill under line */}
            {drawProgress > 0.05 && (
              <path
                d={`${pathD} L ${toSvgX(points[points.length - 1].x)},${CHART_MARGIN.top + CHART_H} L ${toSvgX(points[0].x)},${CHART_MARGIN.top + CHART_H} Z`}
                fill={accentColor}
                opacity={drawProgress * 0.08}
              />
            )}

            {/* Data line */}
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

            {/* Data points */}
            {points.map((p, i) => {
              const pointProgress = interpolate(
                drawProgress,
                [(i / points.length) * 0.8, Math.min(1, (i / points.length) * 0.8 + 0.15)],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              );
              return (
                <circle
                  key={i}
                  cx={toSvgX(p.x)}
                  cy={toSvgY(p.y)}
                  r={6 * pointProgress}
                  fill={accentColor}
                  opacity={pointProgress}
                />
              );
            })}

            {/* X labels */}
            {points.map((p, i) => (
              p.label && (
                <text
                  key={`label-${i}`}
                  x={toSvgX(p.x)}
                  y={CHART_MARGIN.top + CHART_H + 36}
                  fill={muted}
                  fontSize={20}
                  fontFamily={FONTS.ui}
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
