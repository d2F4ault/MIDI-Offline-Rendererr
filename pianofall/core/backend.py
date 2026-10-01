"""
Web engine controller and DOM interaction adapter for HTML5 piano visualizers.

Encapsulates deterministic clock virtualization, canvas compositing,
88-key layout activation, selector overrides, and capture synchronization.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pianofall.backend")

# Deterministic virtual clock + in-page frame-stepped rAF and canvas compositor
DETERMINISTIC_CLOCK_JS = r"""(() => {
  const NativeAC = window.AudioContext || window.webkitAudioContext;
  const nativeRAF = window.requestAnimationFrame.bind(window);
  const nativeCAF = (window.cancelAnimationFrame || function () {}).bind(window);
  const nativePerfNow = performance.now.bind(performance);
  const nativeDateNow = Date.now.bind(Date);

  window.__stepped = false;
  window.__rafQueue = [];
  window.__rafIdCounter = 1;
  window.__virtualAudioSeconds = 0;
  window.__acInstances = [];
  window.__perfFrozenAt = 0;
  window.__perfVirtual0 = 0;
  window.__dateFrozenAt = 0;
  window.__compositeCanvas = null;

  window.requestAnimationFrame = function (cb) {
    if (!window.__stepped) return nativeRAF(cb);
    const id = window.__rafIdCounter++;
    window.__rafQueue.push({ id: id, cb: cb });
    return id;
  };
  window.cancelAnimationFrame = function (id) {
    if (!window.__stepped) return nativeCAF(id);
    window.__rafQueue = window.__rafQueue.filter(function (e) { return e.id !== id; });
  };
  window.webkitRequestAnimationFrame = window.requestAnimationFrame;
  window.webkitCancelAnimationFrame = window.cancelAnimationFrame;

  performance.now = function () {
    if (!window.__stepped) return nativePerfNow();
    return window.__perfFrozenAt + (window.__virtualAudioSeconds * 1000 - window.__perfVirtual0);
  };
  Date.now = function () {
    if (!window.__stepped) return nativeDateNow();
    return window.__dateFrozenAt + (window.__virtualAudioSeconds * 1000 - window.__perfVirtual0);
  };

  function PatchedAC() {
    var args = Array.prototype.slice.call(arguments);
    var inst;
    if (typeof Reflect !== "undefined" && Reflect.construct) {
      inst = Reflect.construct(NativeAC, args);
    } else {
      inst = new NativeAC();
    }
    window.__acInstances.push(inst);
    var desc = Object.getOwnPropertyDescriptor(NativeAC.prototype, "currentTime");
    var nativeGetter = desc && desc.get;
    Object.defineProperty(inst, "currentTime", {
      get: function () {
        if (window.__stepped) return window.__virtualAudioSeconds;
        return nativeGetter ? nativeGetter.call(inst) : 0;
      },
      configurable: true,
    });
    var nativeResume = inst.resume.bind(inst);
    inst.resume = function () {
      if (window.__stepped) return Promise.resolve();
      return nativeResume();
    };
    return inst;
  }
  PatchedAC.prototype = NativeAC.prototype;
  try { Object.setPrototypeOf(PatchedAC, NativeAC); } catch (e) {}
  window.AudioContext = PatchedAC;
  window.webkitAudioContext = PatchedAC;

  window.__drainNativeRAF = function () {
    return new Promise(function (resolve) {
      nativeRAF(function () { nativeRAF(resolve); });
    });
  };

  window.__enterSteppedMode = function () {
    var seed = 0;
    if (window.__acInstances.length && NativeAC) {
      try {
        seed = Object.getOwnPropertyDescriptor(NativeAC.prototype, "currentTime").get.call(window.__acInstances[0]);
      } catch (e) { seed = 0; }
    }
    window.__virtualAudioSeconds = seed;
    window.__perfFrozenAt = nativePerfNow();
    window.__perfVirtual0 = seed * 1000;
    window.__dateFrozenAt = nativeDateNow();
    window.__rafQueue = [];
    window.__stepped = true;
    window.__acInstances.forEach(function (ctx) {
      try { ctx.suspend(); } catch (e) {}
    });
  };

  window.__advanceFrame = function (frameIntervalSeconds) {
    window.__virtualAudioSeconds += frameIntervalSeconds;
    var batch = window.__rafQueue;
    window.__rafQueue = [];
    var ts = window.__perfFrozenAt + (window.__virtualAudioSeconds * 1000 - window.__perfVirtual0);
    for (var i = 0; i < batch.length; i++) {
      try { batch[i].cb(ts); } catch (e) {}
    }
  };

  window.__captureFrame = function () {
    var canvases = Array.from(document.querySelectorAll("canvas")).filter(function (c) {
      return c.offsetParent !== null && c.style.display !== "none";
    });
    canvases.sort(function (a, b) {
      var za = parseInt(getComputedStyle(a).zIndex, 10) || 0;
      var zb = parseInt(getComputedStyle(b).zIndex, 10) || 0;
      return za - zb;
    });
    if (!window.__compositeCanvas) {
      window.__compositeCanvas = document.createElement("canvas");
    }
    var out = window.__compositeCanvas;
    if (out.width !== window.innerWidth || out.height !== window.innerHeight) {
      out.width = window.innerWidth;
      out.height = window.innerHeight;
    }
    var cctx = out.getContext("2d");
    cctx.fillStyle = "#000";
    cctx.fillRect(0, 0, out.width, out.height);
    for (var i = 0; i < canvases.length; i++) {
      try {
        var rect = canvases[i].getBoundingClientRect();
        cctx.drawImage(
          canvases[i],
          Math.round(rect.left),
          Math.round(rect.top),
          Math.round(rect.width),
          Math.round(rect.height)
        );
      } catch (e) {}
    }
    return out.toDataURL("image/png");
  };

  window.__captureThenStep = function (frameIntervalSeconds) {
    var data = window.__captureFrame();
    window.__advanceFrame(frameIntervalSeconds);
    return data;
  };

  // Prevent scrollbars from shifting layout
  window.addEventListener('DOMContentLoaded', () => {
    try {
      const style = document.createElement('style');
      style.textContent = `
        *::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }
        html, body { overflow: hidden !important; margin: 0 !important; padding: 0 !important; width: 100% !important; height: 100% !important; background: #000 !important; }
      `;
      document.head.appendChild(style);
    } catch(e) {}
  });
})();
"""

# Alias for backwards compatibility
AC_CAPTURE_SCRIPT = DETERMINISTIC_CLOCK_JS


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


async def configure_piano_display(page, show_all_88_keys: bool = True) -> None:
    """
    Configure keyboard view to display all 88 keys (A0-C8) and recalibrate canvas layout.
    """
    if show_all_88_keys:
        logger.info("Configuring visualizer to show full 88-key piano keyboard...")
        await page.evaluate(
            """() => {
                const showAll = document.querySelector("#showAllButton")
                    || document.querySelector('button[title*="entire keyboard"]')
                    || document.querySelector('button[title*="Show entire piano"]');
                if (showAll) {
                    showAll.click();
                } else if (typeof window.S === 'function' && typeof window.S().showAll === 'function') {
                    window.S().showAll();
                }
            }"""
        )
        await page.wait_for_timeout(500)

    # Trigger resize event to ensure canvas recalculates full viewport width and height
    await page.evaluate("() => window.dispatchEvent(new Event('resize'))")
    await page.wait_for_timeout(500)


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

    # Hard-hide all overlay elements via DOM style injection and enforce full-bleed viewport
    await page.evaluate(
        """() => {
            const hideSelectors = [
              'button[aria-label="Minimize/Maximize Menu"]',
              'button[aria-label="Open/Close zoom menu"]',
              'button[aria-label="Open settings"]',
              'button[aria-label="Open menu"]',
              '#showAllButton',
              '#fitSongButton',
              '#closeZoomMenuButton',
              '#moveViewLeftButton',
              '#moveViewRightButton',
              '.zoomBtn',
              'header',
              '.top-bar',
              'nav',
              '.menu',
              '#menu',
              '.controls',
              '.floating-controls',
              '.control-bar',
            ];
            for (const sel of hideSelectors) {
              document.querySelectorAll(sel).forEach(el => {
                el.style.display = 'none';
              });
            }

            // Enforce zero margins, zero padding, and pure black background
            const style = document.createElement('style');
            style.id = 'pianofall-fullbleed-override';
            style.textContent = `
              *::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }
              html, body {
                overflow: hidden !important;
                margin: 0 !important;
                padding: 0 !important;
                width: 100vw !important;
                height: 100vh !important;
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                background: #000 !important;
              }
            `;
            document.head.appendChild(style);

            // Notify app to recalculate canvas geometries and piano key coordinates
            try {
              window.dispatchEvent(new Event('resize'));
            } catch (e) {}
        }"""
    )
    # Allow 1 second for resize listener to redraw piano canvases
    await page.wait_for_timeout(1000)
    logger.debug("UI overlays and menu controls hidden; canvas recalibrated.")


async def capture_one_frame(page, capture_mode: str, frame_interval_s: float) -> bytes:
    """
    Capture a single frame from the visualizer and advance the virtual clock by frame_interval_s.
    In 'canvas_composite' mode, composites visible canvases directly onto an offscreen canvas.
    In 'page_screenshot' mode, captures the compositor surface.
    """
    if capture_mode == "canvas_composite":
        data_url = await page.evaluate("(dt) => window.__captureThenStep(dt)", frame_interval_s)
        if not data_url or "," not in data_url:
            raise RuntimeError("Canvas composite capture returned invalid or empty data URL.")
        return base64.b64decode(data_url.split(",", 1)[1])
    else:
        png = await page.screenshot(type="png", full_page=False)
        await page.evaluate("(dt) => window.__advanceFrame(dt)", frame_interval_s)
        return png


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
