#!/usr/bin/env node
/**
 * Render entry point for headless Remotion rendering.
 *
 * Usage:
 *   node render-entry.js \
 *     --composition kpi-counter \
 *     --props '{"label":"ARR","value":25000,"prefix":"$"}' \
 *     --duration 4 \
 *     --output /tmp/remotion_out.mp4 \
 *     [--fps 30] [--width 1920] [--height 1080]
 *
 * Uses Remotion Node API: bundle + getCompositions + renderMedia.
 */
import path from "path";
import { bundle } from "@remotion/bundler";
import { getCompositions, renderMedia } from "@remotion/renderer";

interface RenderArgs {
  composition: string;
  props: Record<string, unknown>;
  duration: number;
  output: string;
  fps: number;
  width: number;
  height: number;
  timeoutMs: number;
}

function parseArgs(): RenderArgs {
  const args = process.argv.slice(2);
  const get = (flag: string, fallback?: string): string => {
    const idx = args.indexOf(flag);
    if (idx === -1 || idx + 1 >= args.length) {
      if (fallback !== undefined) return fallback;
      throw new Error(`Missing required flag: ${flag}`);
    }
    return args[idx + 1];
  };

  return {
    composition: get("--composition"),
    props: JSON.parse(get("--props", "{}")),
    duration: parseFloat(get("--duration", "4")),
    output: get("--output"),
    fps: parseInt(get("--fps", "30"), 10),
    width: parseInt(get("--width", "1920"), 10),
    height: parseInt(get("--height", "1080"), 10),
    timeoutMs: parseInt(get("--timeout", "60000"), 10),
  };
}

async function main() {
  const config = parseArgs();

  const entryPoint = path.resolve(__dirname, "index.ts");

  // Step 1: Bundle the Remotion project
  console.log(`[remotion-render] Bundling ${entryPoint}...`);
  const bundleResult = await bundle({
    entryPoint,
    onProgress: (pct: number) => {
      if (pct % 25 === 0) console.log(`[remotion-render] Bundle progress: ${pct}%`);
    },
  });

  // Step 2: Get compositions to validate the requested one exists
  console.log(`[remotion-render] Getting compositions...`);
  const compositions = await getCompositions(bundleResult, {
    inputProps: config.props,
  });

  const comp = compositions.find((c) => c.id === config.composition);
  if (!comp) {
    const available = compositions.map((c) => c.id).join(", ");
    throw new Error(
      `Composition "${config.composition}" not found. Available: ${available}`
    );
  }

  // Step 3: Render
  const durationInFrames = Math.round(config.duration * config.fps);
  console.log(
    `[remotion-render] Rendering "${config.composition}" ` +
      `(${durationInFrames} frames @ ${config.fps}fps, ${config.width}x${config.height}) ` +
      `→ ${config.output}`
  );

  await renderMedia({
    composition: {
      ...comp,
      durationInFrames,
      fps: config.fps,
      width: config.width,
      height: config.height,
    },
    serveUrl: bundleResult,
    codec: "h264",
    outputLocation: config.output,
    inputProps: config.props,
    timeoutInMilliseconds: config.timeoutMs,
    onProgress: ({ progress }: { progress: number }) => {
      if (Math.round(progress * 100) % 25 === 0) {
        console.log(`[remotion-render] Render progress: ${Math.round(progress * 100)}%`);
      }
    },
  });

  console.log(`[remotion-render] Done: ${config.output}`);
  // Output JSON result for the Python caller to parse
  console.log(
    JSON.stringify({
      status: "success",
      output: config.output,
      composition: config.composition,
      duration_sec: config.duration,
      frames: durationInFrames,
    })
  );
}

main().catch((err) => {
  console.error(`[remotion-render] FATAL: ${err.message}`);
  console.log(JSON.stringify({ status: "error", error: err.message }));
  process.exit(1);
});
