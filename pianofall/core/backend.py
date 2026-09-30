"""
Web engine controller and DOM interaction adapter for HTML5 piano visualizers.

Encapsulates selectors, event listeners, menu-hiding steps, and canvas synchronization.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pianofall.backend")

# AudioContext interception script to monitor and manage web audio instances
AC_CAPTURE_SCRIPT = r"""
(() => {
  const NativeAC = window.AudioContext || window.webkitAudioContext;
  if (NativeAC) {
    window.__acInstances = [];
    function PatchedAC(...args) {
      const inst = new NativeAC(...args);
      window.__acInstances.push(inst);
      return inst;
    }
    PatchedAC.prototype = NativeAC.prototype;
    try { Object.setPrototypeOf(PatchedAC, NativeAC); } catch (e) {}
    window.AudioContext = PatchedAC;
    window.webkitAudioContext = PatchedAC;
  }

  // Prevent browser scrollbars, bars, or margins from shifting canvas content
  window.addEventListener('DOMContentLoaded', () => {
    try {
      const style = document.createElement('style');
      style.textContent = `
        *::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }
        html, body { overflow: hidden !important; margin: 0 !important; padding: 0 !important; width: 100% !important; height: 100% !important; }
      `;
      document.head.appendChild(style);
    } catch(e) {}
  });
})();
"""


async def wait_canvas_ready(page, timeout_ms: int = 60_000) -> None:
    """
    Wait until the piano canvas element is mounted and rendering buffers are prepared.
    """
    logger.debug("Waiting for canvas.pianoCanvas selector...")
    await page.wait_for_selector("canvas.pianoCanvas", timeout=timeout_ms)

    logger.debug("Verifying buffer state and text markers...")
    await page.wait_for_function(
        """() => {
            const t = document.body.innerText || '';
            const pianos = document.querySelectorAll('canvas.pianoCanvas');
            return pianos.length >= 1 && !/Creating Buffers|Phrasing/i.test(t);
        }""",
        timeout=timeout_ms,
    )
    # Allow rendering loop to settle initial frames
    await page.wait_for_timeout(1500)
    logger.debug("Piano canvas is fully initialized and ready.")


async def upload_midi_file(page, midi_path: Path, timeout_sec: float = 180.0) -> None:
    """
    Locate file input element, attach MIDI file, and wait for buffer parsing.
    """
    buffers_event = asyncio.Event()

    def on_console(msg) -> None:
        text = msg.text or ""
        if "Buffers loaded" in text or "Setting song" in text:
            buffers_event.set()

    page.on("console", on_console)
    try:
        file_input = page.locator('input[type="file"][accept*=".mid"]').first
        await file_input.wait_for(state="attached", timeout=30_000)
        logger.info(f"Uploading MIDI file: {midi_path.name}")
        await file_input.set_input_files(str(midi_path))

        try:
            await asyncio.wait_for(buffers_event.wait(), timeout=timeout_sec)
            logger.debug("Buffer loaded console event confirmed.")
        except asyncio.TimeoutError:
            logger.warning("No buffer load event received on console; falling back to canvas readiness check.")

        await wait_canvas_ready(page)
    finally:
        try:
            if hasattr(page, "remove_listener"):
                page.remove_listener("console", on_console)
            elif hasattr(page, "off"):
                page.off("console", on_console)
        except Exception:
            pass


async def dismiss_popups(page) -> None:
    """Dismiss any modal dialogs, cookie notices, or consent banners."""
    try:
        await page.evaluate(
            """() => {
                const dismiss = [
                    'button[aria-label="Close"]',
                    'button:has-text("OK")',
                    'button:has-text("Got it")',
                    'button:has-text("Dismiss")',
                    '.modal-close',
                    '.cookie-notice button',
                ];
                for (const sel of dismiss) {
                    try {
                        const el = document.querySelector(sel);
                        if (el && el.offsetParent !== null) el.click();
                    } catch(e) {}
                }
            }"""
        )
    except Exception:
        pass


async def hide_navigation_overlays(page, viewport_w: int, viewport_h: int) -> None:
    """
    Collapse top menu bars, hide hovering controls, and dismiss UI overlays for a pristine render.
    """
    btn = page.locator('button[aria-label="Minimize/Maximize Menu"]')
    if await btn.count() and await btn.first.is_visible():
        try:
            await btn.first.click(timeout=5_000)
            logger.debug("Clicked minimize menu button.")
        except Exception as e:
            logger.warning(f"Could not click minimize menu button: {e}")

    # Move cursor to center so hover chevrons and tooltips fade out
    await page.mouse.move(viewport_w // 2, viewport_h // 2)
    # Wait 4 seconds for native CSS fade transition to finish
    await page.wait_for_timeout(4000)

    # Hard-hide all overlay elements via DOM style injection
    await page.evaluate(
        """() => {
            const hideSelectors = [
              'button[aria-label="Minimize/Maximize Menu"]',
              'button[aria-label="Open/Close zoom menu"]',
              'button[aria-label="Open settings"]',
              'button[aria-label="Open menu"]',
              'header',
              '.top-bar',
              'nav',
            ];
            for (const sel of hideSelectors) {
              document.querySelectorAll(sel).forEach(el => {
                el.style.display = 'none';
              });
            }
            document.documentElement.style.overflow = 'hidden';
            document.body.style.overflow = 'hidden';
            document.body.style.margin = '0';
            document.body.style.padding = '0';
        }"""
    )
    logger.debug("UI overlays and menu controls hidden.")


async def trigger_playback(page) -> None:
    """Send Space key to initiate falling notes playback."""
    logger.debug("Dispatching Space keydown to initiate playback.")
    await page.keyboard.press("Space")


async def capture_debug_screenshot(page, dest_path: Path) -> Optional[Path]:
    """Capture a diagnostic screenshot if an unhandled error occurs during rendering."""
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(dest_path))
        logger.info(f"Diagnostic screenshot saved to {dest_path}")
        return dest_path
    except Exception as e:
        logger.warning(f"Failed to capture debug screenshot: {e}")
        return None
