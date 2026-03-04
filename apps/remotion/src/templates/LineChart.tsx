import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import { FadeIn, HeroStack, CornerBadge, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE, TEXT_STYLES } from "../design-system";

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
  variant?: "swishy" | "chart";
}

const CHART_MARGIN = { top: 40, right: 60, bottom: 60, left: 60 };
const CHART_W = 1920 - 280 - CHART_MARGIN.left - CHART_MARGIN.right; // padded for left layout
const CHART_H = 420;
const SVG_W = CHART_W + CHART_MARGIN.left + CHART_MARGIN.right;
const SVG_H = CHART_H + CHART_MARGIN.top + CHART_MARGIN.bottom;

export const LineChart: React.FC<LineChartProps> = ({
  title,
  points,
  yLabel,
  accentColor = PALETTE.default_accent,
  bg = "dark",
  variant = "swishy",
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const foreground = fgColor(bg);
  const muted = PALETTE.muted;
  const bgStyle = proBgStyle(bg, accentColor);
  const isSwishy = variant === "swishy";

  if (!points.length) return <AbsoluteFill style={{ backgroundColor: PALETTE.dark_bg }} />;

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const lastY = points[points.length - 1].y;

  const drawProgress = interpolate(frame, [8, Math.min(36, durationInFrames - 6)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const toSvgX = (x: number) => CHART_MARGIN.left + ((x - minX) / rangeX) * CHART_W;
  const toSvgY = (y: number) => CHART_MARGIN.top + CHART_H - ((y - minY) / rangeY) * CHART_H;

  const pathPoints = points.map((p) => `${toSvgX(p.x)},${toSvgY(p.y)}`);
  const pathD = `M ${pathPoints.join(" L ")}`;

  // Area fill path
  const areaD = `${pathD} L ${toSvgX(points[points.length - 1].x)},${CHART_MARGIN.top + CHART_H} L ${toSvgX(points[0].x)},${CHART_MARGIN.top + CHART_H} Z`;

  let totalLen = 0;
  for (let i = 1; i < points.length; i++) {
    const dx = toSvgX(points[i].x) - toSvgX(points[i - 1].x);
    const dy = toSvgY(points[i].y) - toSvgY(points[i - 1].y);
    totalLen += Math.sqrt(dx * dx + dy * dy);
  }

  const glowOpacity = interpolate(drawProgress, [0, 0.3], [0, 0.35], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  const areaOpacity = interpolate(drawProgress, [0.1, 0.6], [0, 0.15], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  const formattedLast = lastY.toLocaleString();
  const heroValue = yLabel === "$" || title.toLowerCase().includes("cost") || title.toLowerCase().includes("revenue")
    ? `$${formattedLast}` : formattedLast;

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        {/* Swishy: HeroStack top-left + badge */}
        {isSwishy && (
          <>
            <div style={{ position: "absolute", top: 80, left: 140, zIndex: 2 }}>
              <HeroStack
                label={title}
                value={heroValue}
                ghostValue={heroValue}
                accentColor={accentColor}
                align="left"
              />
            </div>
            <CornerBadge label={yLabel || title.substring(0, 12).toUpperCase()} value={heroValue} />
          </>
        )}

        {/* Chart title for chart variant */}
        {!isSwishy && (
          <FadeIn durationFrames={10}>
            <h1
              style={{
                color: foreground,
                fontSize: TYPE_SCALE.title,
                fontWeight: 700,
                marginBottom: 20,
                textAlign: "left",
                fontFamily: FONTS.display,
              }}
            >
              {title}
            </h1>
          </FadeIn>
        )}

        {/* Chart SVG — positioned lower in swishy mode */}
        <div style={{
          position: isSwishy ? "absolute" : "relative",
          bottom: isSwishy ? 60 : undefined,
          left: isSwishy ? 100 : undefined,
          right: isSwishy ? 100 : undefined,
        }}>
          <svg width={SVG_W} height={SVG_H} viewBox={`0 0 ${SVG_W} ${SVG_H}`}>
            <defs>
              <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={accentColor} stopOpacity={0.3} />
                <stop offset="100%" stopColor={accentColor} stopOpacity={0} />
              </linearGradient>
              <filter id="lineGlow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="8" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <filter id="lineGlowMedium" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="4" />
              </filter>
            </defs>

            {/* Axes (only in chart mode) */}
            {!isSwishy && (
              <>
                <line x1={CHART_MARGIN.left} y1={CHART_MARGIN.top} x2={CHART_MARGIN.left} y2={CHART_MARGIN.top + CHART_H} stroke={muted} strokeWidth={1} opacity={0.2} />
                <line x1={CHART_MARGIN.left} y1={CHART_MARGIN.top + CHART_H} x2={CHART_MARGIN.left + CHART_W} y2={CHART_MARGIN.top + CHART_H} stroke={muted} strokeWidth={1} opacity={0.2} />
              </>
            )}

            {/* Area fill under line */}
            <path d={areaD} fill="url(#areaFill)" opacity={areaOpacity} />

            {/* 3-pass glow stack: fat blur */}
            <path d={pathD} fill="none" stroke={accentColor} strokeWidth={20} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={totalLen} strokeDashoffset={totalLen * (1 - drawProgress)} opacity={glowOpacity * 0.4} filter="url(#lineGlow)" />
            {/* Medium blur */}
            <path d={pathD} fill="none" stroke={accentColor} strokeWidth={10} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={totalLen} strokeDashoffset={totalLen * (1 - drawProgress)} opacity={glowOpacity * 0.6} filter="url(#lineGlowMedium)" />
            {/* Sharp line */}
            <path d={pathD} fill="none" stroke={accentColor} strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={totalLen} strokeDashoffset={totalLen * (1 - drawProgress)} />

            {/* Data points */}
            {points.map((p, i) => {
              const pp = interpolate(
                drawProgress,
                [(i / points.length) * 0.8, Math.min(1, (i / points.length) * 0.8 + 0.15)],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              );
              return (
                <React.Fragment key={i}>
                  <circle cx={toSvgX(p.x)} cy={toSvgY(p.y)} r={12 * pp} fill={accentColor} opacity={pp * 0.2} />
                  <circle cx={toSvgX(p.x)} cy={toSvgY(p.y)} r={5 * pp} fill={accentColor} opacity={pp} />
                </React.Fragment>
              );
            })}

            {/* X labels (chart mode only) */}
            {!isSwishy && points.map((p, i) => (
              p.label && (
                <text key={`label-${i}`} x={toSvgX(p.x)} y={CHART_MARGIN.top + CHART_H + 35} fill={muted} fontSize={TYPE_SCALE.caption} textAnchor="middle" fontFamily={FONTS.ui}>
                  {p.label}
                </text>
              )
            ))}
          </svg>
        </div>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
