import React, { useEffect } from "react";
import { Composition } from "remotion";
// Load fonts BEFORE any composition renders
import { waitForFonts } from "./fonts";
import { DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS } from "./design-system";

import { KpiCounter } from "./templates/KpiCounter";
import type { KpiCounterProps } from "./templates/KpiCounter";
import { KpiChart } from "./templates/KpiChart";
import type { KpiChartProps } from "./templates/KpiChart";
import { LineChart } from "./templates/LineChart";
import type { LineChartProps } from "./templates/LineChart";
import { QuoteHighlight } from "./templates/QuoteHighlight";
import type { QuoteHighlightProps } from "./templates/QuoteHighlight";
import { StepsList } from "./templates/StepsList";
import type { StepsListProps } from "./templates/StepsList";
import { ProfileCard } from "./templates/ProfileCard";
import type { ProfileCardProps } from "./templates/ProfileCard";
import { CodeCard } from "./templates/CodeCard";
import type { CodeCardProps } from "./templates/CodeCard";
import { CustomScene } from "./templates/CustomScene";
import type { CustomSceneProps } from "./templates/CustomScene";

const DEFAULT_DURATION_SEC = 4;

/**
 * Wrapper that blocks rendering until Google Fonts are loaded.
 */
const FontGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  useEffect(() => {
    const cleanup = waitForFonts();
    return cleanup;
  }, []);
  return <>{children}</>;
};

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="kpi-counter"
        component={KpiCounter}
        durationInFrames={DEFAULT_DURATION_SEC * DEFAULT_FPS}
        fps={DEFAULT_FPS}
        width={DEFAULT_WIDTH}
        height={DEFAULT_HEIGHT}
        defaultProps={{
          label: "Revenue",
          value: 25000,
          prefix: "$",
          bg: "dark" as const,
        }}
      />

      <Composition
        id="kpi-chart"
        component={KpiChart}
        durationInFrames={DEFAULT_DURATION_SEC * DEFAULT_FPS}
        fps={DEFAULT_FPS}
        width={DEFAULT_WIDTH}
        height={DEFAULT_HEIGHT}
        defaultProps={{
          label: "EXPENSES",
          value: 5000,
          prefix: "$",
          points: [
            { x: 0, y: 500 },
            { x: 1, y: 1200 },
            { x: 2, y: 2800 },
            { x: 3, y: 5000 },
          ],
          bg: "dark" as const,
        }}
      />

      <Composition
        id="line-chart"
        component={LineChart}
        durationInFrames={DEFAULT_DURATION_SEC * DEFAULT_FPS}
        fps={DEFAULT_FPS}
        width={DEFAULT_WIDTH}
        height={DEFAULT_HEIGHT}
        defaultProps={{
          title: "Growth",
          points: [
            { x: 0, label: "Q1", y: 10 },
            { x: 1, label: "Q2", y: 25 },
            { x: 2, label: "Q3", y: 45 },
            { x: 3, label: "Q4", y: 80 },
          ],
          bg: "dark" as const,
        }}
      />

      <Composition
        id="quote-highlight"
        component={QuoteHighlight}
        durationInFrames={DEFAULT_DURATION_SEC * DEFAULT_FPS}
        fps={DEFAULT_FPS}
        width={DEFAULT_WIDTH}
        height={DEFAULT_HEIGHT}
        defaultProps={{
          quote: "The best way to predict the future is to create it.",
          attribution: "Peter Drucker",
          bg: "dark" as const,
        }}
      />

      <Composition
        id="steps-list"
        component={StepsList}
        durationInFrames={DEFAULT_DURATION_SEC * DEFAULT_FPS}
        fps={DEFAULT_FPS}
        width={DEFAULT_WIDTH}
        height={DEFAULT_HEIGHT}
        defaultProps={{
          title: "How It Works",
          steps: ["Sign up", "Connect your data", "Get insights"],
          bg: "dark" as const,
        }}
      />

      <Composition
        id="profile-card"
        component={ProfileCard}
        durationInFrames={DEFAULT_DURATION_SEC * DEFAULT_FPS}
        fps={DEFAULT_FPS}
        width={DEFAULT_WIDTH}
        height={DEFAULT_HEIGHT}
        defaultProps={{
          name: "Jane Doe",
          title: "CEO & Founder",
          bullets: ["10+ years experience", "Forbes 30 Under 30"],
          bg: "dark" as const,
        }}
      />

      <Composition
        id="code-card"
        component={CodeCard}
        durationInFrames={DEFAULT_DURATION_SEC * DEFAULT_FPS}
        fps={DEFAULT_FPS}
        width={DEFAULT_WIDTH}
        height={DEFAULT_HEIGHT}
        defaultProps={{
          title: "Hello World",
          code: 'const greet = (name) => {\n  return `Hello, ${name}!`;\n};',
          bg: "dark" as const,
        }}
      />

      <Composition
        id="custom"
        component={CustomScene}
        durationInFrames={DEFAULT_DURATION_SEC * DEFAULT_FPS}
        fps={DEFAULT_FPS}
        width={DEFAULT_WIDTH}
        height={DEFAULT_HEIGHT}
        defaultProps={{
          spec: {
            scene_kind: "headline_highlight" as const,
            duration_sec: 4,
            bg: "dark" as const,
            accent_color: "#4F8CFF",
            typography: {
              primary_font: "Inter",
              mono_font: "SF Mono",
              max_families: 2,
            },
            elements: [
              {
                type: "text" as const,
                layout: "center" as const,
                text: "Custom Scene",
                animation_primitives: ["FadeIn" as const],
              },
            ],
            allowed_primitives: ["FadeIn" as const],
            hard_limits: {
              max_elements: 8,
              max_simultaneous_animations: 3,
              max_accent_colors: 1,
            },
          },
        }}
      />
    </>
  );
};
