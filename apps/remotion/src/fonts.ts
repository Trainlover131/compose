/**
 * Font loading for Remotion render environment.
 * Uses @remotion/google-fonts to guarantee fonts are available before rendering.
 *
 * We use delayRender/continueRender to BLOCK frame rendering until fonts
 * are fully downloaded. This prevents Chromium from falling back to its
 * default serif font (Times New Roman) on first frames.
 */
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadSpaceGrotesk } from "@remotion/google-fonts/SpaceGrotesk";
import { continueRender, delayRender } from "remotion";

// Load both fonts — these register @font-face rules immediately
const interResult = loadInter();
const spaceGroteskResult = loadSpaceGrotesk();

export const interFamily = interResult.fontFamily;
export const spaceGroteskFamily = spaceGroteskResult.fontFamily;

/**
 * Call this inside a React effect to block rendering until fonts are ready.
 * Returns a cleanup function.
 */
export function waitForFonts(): () => void {
  const handle = delayRender("Waiting for Google Fonts to load");

  Promise.all([
    interResult.waitUntilDone(),
    spaceGroteskResult.waitUntilDone(),
  ])
    .then(() => {
      continueRender(handle);
    })
    .catch((err) => {
      console.error("[fonts] Failed to load fonts, continuing anyway:", err);
      continueRender(handle);
    });

  return () => {
    // If component unmounts before fonts load, release the handle
    try {
      continueRender(handle);
    } catch {
      // Already continued — ignore
    }
  };
}
