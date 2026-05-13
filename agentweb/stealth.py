"""Stealth layer for AgentWeb's browser automation.

Applies anti-detection countermeasures at the browser/JS layer:
canvas fingerprint randomization, navigator property spoofing,
automation flag suppression, timing humanization, and referrer spoofing.

Usage:
    from agentweb.stealth import StealthMiddleware, get_stealth_preset

    config = get_stealth_preset("aggressive")
    middleware = StealthMiddleware(config)
    page.add_init_script(middleware.stealth_script())
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Indentation helper ────────────────────────────────────────────────────────


def _j(indent: str, block: str) -> str:
    """Indent a raw JS text block. No f-string brace escaping needed."""
    if not block.strip():
        return ""
    return "\n".join(indent + line for line in block.split("\n"))


# ── Enums & Config ────────────────────────────────────────────────────────────


class StealthLevel(Enum):
    OFF = "off"
    STANDARD = "standard"
    AGGRESSIVE = "aggressive"


def _default_ua() -> str:
    """Return a realistic Chrome UA string with randomized version."""
    major = random.choice([124, 125, 126])
    minor = random.randint(0, 9)
    patch = random.randint(0, 99)
    build = random.randint(1000, 9999)
    rev = random.randint(100, 999)
    return (
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.{minor}.{patch} "
        f"Safari/537.36"
    )


@dataclass
class StealthConfig:
    """Configuration for stealth countermeasures."""

    level: StealthLevel = StealthLevel.STANDARD

    # Canvas / WebGL
    randomize_canvas: bool = False
    randomize_webgl: bool = False

    # Navigator properties
    spoof_navigator_props: bool = False
    spoof_plugins: bool = False
    spoof_languages: bool = False

    # Environment
    randomize_timezone: bool = False
    spoof_referrer: bool = False
    random_viewport: bool = False

    # Mouse / timing (Camoufox handles this; flag for docs)
    mouse_humanization: bool = True

    # Automation detection
    suppress_automation_flags: bool = False
    spoof_chrome_runtime: bool = False
    spoof_permissions: bool = False
    spoof_ua: bool = False

    # Canvas noise seed (randomized per session)
    canvas_noise_seed: int = field(default_factory=lambda: random.randint(0, 2**32 - 1))

    # Fake UA string (set per session in AGGRESSIVE mode)
    fake_ua: str = field(default_factory=_default_ua)


def _default_ua_runner() -> str:
    """Return a realistic Chrome UA string with randomized version."""
    major = random.choice([124, 125, 126])
    minor = random.randint(0, 9)
    patch = random.randint(0, 99)
    build = random.randint(1000, 9999)
    rev = random.randint(100, 999)
    return (
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.{minor}.{patch} "
        f"Safari/537.36"
    )


# ── Preset Factory ───────────────────────────────────────────────────────────


def get_stealth_preset(level: str) -> StealthConfig:
    """Map a string level name to a fully-populated StealthConfig.

    Args:
        level: One of "off", "standard", "aggressive"

    Returns:
        StealthConfig with the appropriate flags set
    """
    if level in ("off", "none", "disabled"):
        return StealthConfig(level=StealthLevel.OFF)

    if level == "aggressive":
        return StealthConfig(
            level=StealthLevel.AGGRESSIVE,
            randomize_canvas=True,
            randomize_webgl=True,
            spoof_navigator_props=True,
            spoof_plugins=True,
            spoof_languages=True,
            randomize_timezone=True,
            spoof_referrer=True,
            suppress_automation_flags=True,
            spoof_chrome_runtime=True,
            spoof_permissions=True,
            spoof_ua=True,
        )

    # Default: standard
    return StealthConfig(
        level=StealthLevel.STANDARD,
        spoof_navigator_props=True,
        spoof_languages=True,
        suppress_automation_flags=True,
        spoof_permissions=True,
    )


# ── JS Block Builders ────────────────────────────────────────────────────────


def _build_suppress_automation() -> str:
    return _j("    ", """\
// Suppress navigator.webdriver and domAutomation controller
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
    enumerable: true
});

// Remove chrome automation / CDP endpoints
delete navigator.__webdriver_evaluate;
delete navigator.__webdriver_script_function;
delete navigator.__webdriver_script_fn_args;
delete navigator.__webdriver_script_code;
delete navigator.__webdriver_collected_scripts;
delete navigator.__webdriver_resolve_or_promise;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
delete window.$cdc_asdjflasutopfhvcZLmcfl_;
delete window.$chrome_asyncScriptInfo;""")


def _build_navigator_props() -> str:
    return _j("    ", """\
// Spoof maxTouchPoints to look like a real laptop (avoids headless=0 flag)
Object.defineProperty(navigator, 'maxTouchPoints', {
    get: () => 0,
    configurable: true
});

// Spoof hardware concurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
    configurable: true
});""")


def _build_languages() -> str:
    return _j("    ", """\
// Spoof languages to look realistic
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en', 'es'],
    configurable: true
});
Object.defineProperty(navigator, 'language', {
    get: () => 'en-US',
    configurable: true
});""")


def _build_plugins() -> str:
    return _j("    ", """\
// Spoof plugins array to match a real Chrome install
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', description: 'Portable Document Format', filename: 'internal-pdf-viewer', 0: {}},
        { name: 'Chrome PDF Viewer',  description: '', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', 0: {}},
        { name: 'Native Client',       description: '', filename: 'internal-nacl-plugin', 0: {}}
    ],
    configurable: true,
    enumerable: true
});
Object.defineProperty(navigator, 'mimeTypes', {
    get: () => [
        { type: 'application/pdf', suffixes: 'pdf', description: '' },
        { type: 'application/x-nacl', suffixes: '', description: '' },
        { type: 'application/x-pnacl', suffixes: '', description: '' }
    ],
    configurable: true,
    enumerable: true
});""")


def _build_chrome_runtime() -> str:
    return _j("    ", """\
// Spoof window.chrome runtime to look like regular Chrome (not headless)
Object.defineProperty(window, 'chrome', {
    get: () => ({
        app: { isInstalled: false },
        runtime: { id: null, manifest: {} },
        loadTimes: function() { return {}; },
        csi: function() { return {}; },
        webstore: {}
    }),
    configurable: true,
    enumerable: false
});""")


def _build_canvas_noise(seed: int) -> str:
    return _j("    ", """\
// Randomize canvas fingerprint by injecting noise into getImageData and toDataURL
(function() {
    // Linear-congruential RNG seeded per-session for consistent noise within a session
    // but different noise across sessions (different seed each browser launch).
    var _s = %s;
    function _rng() {
        _s = (Math.imul(1664525, _s) + 1013904223) >>> 0;
        return _s / 0xFFFFFFFF;
    }
    function _add_noise(data) {
        for (var i = 0; i < data.length; i += 4) {
            data[i]     = Math.min(255, Math.max(0, data[i]     + Math.floor(_rng() * 6 - 3)));
            data[i + 1] = Math.min(255, Math.max(0, data[i + 1] + Math.floor(_rng() * 6 - 3)));
            data[i + 2] = Math.min(255, Math.max(0, data[i + 2] + Math.floor(_rng() * 6 - 3)));
        }
    }

    var _origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attrs) {
        var ctx = _origGetContext.call(this, type, attrs);
        if (type !== '2d') return ctx;

        // Capture ORIGINAL getImageData — NOT the overridden one, to avoid
        // double-noise when toDataURL reads back pixel data.
        var _rawGetImageData = CanvasRenderingContext2D.prototype.getImageData;
        if (!_rawGetImageData) _rawGetImageData = ctx.getImageData.bind(ctx);

        var _origToDataURL = this.toDataURL.bind(this);

        // Override getImageData to add per-pixel noise to RGB channels
        this.getImageData = function(sx, sy, sw, sh) {
            var imgData = _rawGetImageData.call(this, sx, sy, sw, sh);
            _add_noise(imgData.data);
            return imgData;
        };
        ctx.getImageData = this.getImageData;

        // Override toDataURL to catch fingerprinters that skip getImageData
        // and read pixels directly via toDataURL. We draw to an offscreen
        // canvas, read back with the RAW getImageData (no double-noise),
        // apply noise once, then call the original toDataURL.
        this.toDataURL = function() {
            var tmpCanvas = document.createElement('canvas');
            tmpCanvas.width = this.width;
            tmpCanvas.height = this.height;
            var tmpCtx = tmpCanvas.getContext('2d');
            try { tmpCtx.drawImage(this, 0, 0); } catch(e) {}
            var imgData;
            try { imgData = _rawGetImageData.call(tmpCtx, 0, 0, this.width, this.height); } catch(e) {}
            if (imgData) {
                _add_noise(imgData.data);
                try { tmpCtx.putImageData(imgData, 0, 0); } catch(e) {}
            }
            return _origToDataURL.call(this);
        };
        return ctx;
    };
})();""" % (seed & 0xFFFFFFFF))


def _build_webgl_spoof() -> str:
    return _j("    ", """\
// Spoof WebGL renderer to avoid "SwiftShader" / "llvmpipe" headless flags
(function() {
    var _origGetParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        // UNMASKED_RENDERER_WEBGL (37445) — return realistic GPU
        if (param === 37445) { return 'Intel Iris OpenGL Engine'; }
        // UNMASKED_VENDOR_WEBGL (37446)
        if (param === 37446) { return 'Intel Inc.'; }
        // RENDERER (contributes to fingerprint)
        if (param === 7936)  { return 'Apple GPU'; }
        return _origGetParameter.call(this, param);
    };

    // Also patch WebGL2 context
    if (typeof WebGL2RenderingContext !== 'undefined') {
        var _origGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(param) {
            if (param === 37445) return 'Intel Iris OpenGL Engine';
            if (param === 37446) return 'Intel Inc.';
            if (param === 7936)  return 'Apple GPU';
            return _origGetParameter2.call(this, param);
        };
    }
})();""")


def _build_timing_spoof() -> str:
    return _j("    ", """\
// Spoof timing APIs to prevent clock-skew fingerprinting and timing-based detection.
// Adds sub-millisecond jitter to performance.now() and Date.now() values.
(function() {
    var _jitter = Math.floor(Math.random() * 20 + 1) * 0.1;  // 0.1-2.0ms constant offset

    // Spoof performance.now() — add jitter so deterministic render timings can't be fingerprinted
    var _origNow = performance.now.bind(performance);
    performance.now = function() {
        return _origNow() + _jitter + (Math.random() * 0.5 - 0.25);
    };

    // Spoof Date.now() with same jitter (some detectors compare both for consistency)
    var _origDateNow = Date.now.bind(Date);
    Date.now = function() {
        return _origDateNow() + Math.floor(_jitter);
    };
})();""")


def _build_permissions_spoof() -> str:
    return _j("    ", """\
// Spoof permissions.query to return 'granted' for everything
(function() {
    var _origQuery = (navigator.permissions && navigator.permissions.query);
    if (!_origQuery) return;
    navigator.permissions.query = function(origin) {
        return _origQuery.call(navigator.permissions, origin)
            .then(function(result) {
                Object.defineProperty(result, 'state', {
                    get: function() { return 'granted'; },
                    configurable: true
                });
                return result;
            });
    };
})();""")


def _build_referrer_spoof() -> str:
    return _j("    ", """\
// Neutralize referrer leakage by overriding document.referrer getter
Object.defineProperty(document, 'referrer', {
    get: function() { return 'https://www.google.com/search?q=agentweb'; },
    configurable: true
});""")


def _build_ua_spoof(ua: str) -> str:
    return _j("    ", (
        "// Set navigator.userAgent to match the launch arg\n"
        "Object.defineProperty(navigator, 'userAgent', {\n"
        "    get: function() { return '" + ua + "'; },\n"
        "    configurable: true\n"
        "});"
    ))


def _build_cdp_cleanup() -> str:
    return _j("    ", """\
// Remove all known CDP automation globals that fingerprinting scripts check
(function() {
    var chromeProps = Object.getOwnPropertyNames(window).filter(function(k) {
        return /^(cdc_|\\$cdc_|__webdriver|domAutomation|webdriver)/.test(k);
    });
    chromeProps.forEach(function(prop) {
        try { delete window[prop]; } catch(e) {}
    });
})();""")


# ── JS Generation ────────────────────────────────────────────────────────────


def generate_stealth_js(config: StealthConfig) -> str:
    """Generate JavaScript for page injection based on stealth config.

    Args:
        config: StealthConfig describing which countermeasures to apply

    Returns:
        JavaScript string to inject via page.add_init_script()
    """
    if config.level == StealthLevel.OFF:
        return ""

    blocks: list[str] = []

    blocks.append("(function() {")
    blocks.append("    'use strict';")

    if config.suppress_automation_flags:
        blocks.append(_build_suppress_automation())

    if config.spoof_navigator_props:
        blocks.append(_build_navigator_props())

    if config.spoof_languages:
        blocks.append(_build_languages())

    if config.spoof_plugins:
        blocks.append(_build_plugins())

    if config.spoof_chrome_runtime:
        blocks.append(_build_chrome_runtime())

    if config.randomize_canvas:
        blocks.append(_build_canvas_noise(config.canvas_noise_seed))

    if config.randomize_webgl:
        blocks.append(_build_webgl_spoof())

    if config.spoof_permissions:
        blocks.append(_build_permissions_spoof())

    if config.spoof_referrer:
        blocks.append(_build_referrer_spoof())

    if config.spoof_ua:
        blocks.append(_build_ua_spoof(config.fake_ua))

    if config.level == StealthLevel.AGGRESSIVE:
        blocks.append(_build_timing_spoof())

    # CDP cleanup runs always when any stealth is active
    if config.level != StealthLevel.OFF:
        blocks.append(_build_cdp_cleanup())

    blocks.append("})();")

    return "\n".join(blocks)


# ── Middleware ────────────────────────────────────────────────────────────────


@dataclass
class StealthMiddleware:
    """Browser-layer stealth middleware for Camoufox.

    Wraps a StealthConfig and provides:
    - stealth_script(): JS injection script for page.add_init_script()
    - stealth_args(): browser launch arguments for anti-detection
    """

    config: StealthConfig

    def stealth_script(self) -> str:
        """Return the JS injection script for this config."""
        return generate_stealth_js(self.config)

    def stealth_args(self) -> list[str]:
        """Return browser launch arguments for stealth.

        These should be passed to Camoufox(..., args=[...])
        or as Chromium launch args.
        """
        if self.config.level == StealthLevel.OFF:
            return []

        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-extensions",
            "--disable-dev-shm-usage",
        ]

        if self.config.suppress_automation_flags:
            args.extend([
                "--disable-automation-extension",
                "--no-first-run",
            ])

        if self.config.spoof_ua:
            args.append(f"--user-agent={self.config.fake_ua}")

        return args

    def stealth_page_setup(self, page: Any) -> None:
        """Apply stealth countermeasures to a Camoufox page.

        Args:
            page: Camoufox page instance (playwright.sync_api.Page compatible)
        """
        script = self.stealth_script()
        if script:
            page.add_init_script(script)


# ── Validation ───────────────────────────────────────────────────────────────


def validate_stealth_neutralized(page: Any) -> dict[str, Any]:
    """Query the page for detection signals and return a neutralization report.

    Args:
        page: Camoufox page with content already loaded

    Returns:
        dict with keys:
            - webdriver_flag: bool (True = detected)
            - automation_flags: list[str]
            - chrome_object: bool
            - canvas_fingerprint: str (base64-encoded canvas fingerprint for comparison)
            - status: "clean" | "suspicious" | "detected"
    """
    try:
        signals = page.evaluate("""\
            function() {
                var issues = [];
                if (navigator.webdriver === true) issues.push('navigator.webdriver=true');
                var chromeKeys = Object.keys(window).filter(function(k) {
                    return k.includes('chrome') || k.includes('__webdriver') ||
                           k.includes('cdc_') || k.includes('domAutomation');
                });
                // Canvas fingerprint probe
                var canvasFP = "";
                try {
                    var c = document.createElement('canvas');
                    c.width = 200;
                    c.height = 50;
                    var ctx = c.getContext('2d');
                    ctx.textBaseline = 'top';
                    ctx.font = '14px Arial';
                    ctx.fillStyle = '#f60';
                    ctx.fillRect(125, 1, 62, 20);
                    ctx.fillStyle = '#069';
                    ctx.fillText('Cwm fjordbank glyphs vext quiz, 😃', 2, 15);
                    canvasFP = c.toDataURL();
                } catch(e) { canvasFP = 'error:' + e.message; }
                return {
                    webdriver_flag: navigator.webdriver === true,
                    automation_flags: issues,
                    chrome_object: typeof window.chrome === 'object',
                    chrome_keys: chromeKeys,
                    touch_points: navigator.maxTouchPoints,
                    hardware_concurrency: navigator.hardwareConcurrency,
                    ua_prefix: navigator.userAgent.substring(0, 80),
                    canvas_fingerprint: canvasFP.substring(0, 200),
                    languages: navigator.languages ? navigator.languages.join(',') : '',
                    plugins_count: navigator.plugins ? navigator.plugins.length : 0,
                };
            }
        """)
    except Exception as exc:
        return {"error": str(exc), "status": "unknown"}

    status = "clean"
    if len(signals.get("automation_flags", [])) > 0 or signals.get("webdriver_flag"):
        status = "detected"
    elif signals.get("chrome_keys") and len(signals["chrome_keys"]) > 0:
        status = "suspicious"

    return {**signals, "status": status}


def run_stealth_validation(
    stealth_level: str = "aggressive",
    url: str = "",
) -> dict[str, Any]:
    """Launch a headless browser with stealth and validate detection signals.

    Starts a headless Camoufox with the given stealth level, navigates
    to about:blank (or an optional URL), and runs the detection-signal
    evaluation. Returns a full neutralization report.

    This is the primary entry point for the ``agentweb validate`` CLI command.
    """
    report: dict[str, Any] = {
        "stealth_level": stealth_level,
        "detection_signals": {},
    }
    try:
        from camoufox.sync_api import Camoufox

        stealth_js = stealth_script_for_level(stealth_level)
        config = get_stealth_preset(stealth_level)
        middleware = StealthMiddleware(config)

        with Camoufox(
            headless=True,
            humanize=True,
            args=middleware.stealth_args() or None,
        ) as browser:
            page = browser.new_page()
            if stealth_js:
                page.add_init_script(stealth_js)
            nav_url = url or "about:blank"
            page.goto(nav_url, wait_until="domcontentloaded", timeout=15000)
            report["detection_signals"] = validate_stealth_neutralized(page)

            # If a real URL was provided, also check page content for block patterns
            if url:
                body_text = page.locator("body").inner_text(timeout=5000).lower()
                block_keywords = [
                    "automated", "bot", "captcha", "verify", "unusual traffic",
                    "enable javascript", "please wait", "challenge",
                ]
                blocked = [kw for kw in block_keywords if kw in body_text]
                if blocked:
                    report["content_blocked"] = True
                    report["block_keywords_found"] = blocked
                else:
                    report["content_blocked"] = False

    except ImportError:
        report["error"] = "Camoufox not installed — run: uv add camoufox"
        report["status"] = "error"
    except Exception as exc:
        report["error"] = str(exc)
        report["status"] = "error"
    else:
        # Derive overall status
        sig = report["detection_signals"]
        if sig.get("status") == "clean":
            report["status"] = "passed"
        elif sig.get("status") == "detected":
            report["status"] = "failed"
        elif sig.get("status") == "suspicious":
            report["status"] = "suspicious"
        else:
            report["status"] = "passed"

    return report


# ── Convenience ──────────────────────────────────────────────────────────────


def stealth_script_for_level(level: str) -> str:
    """One-liner: get stealth JS for a level string.

    Example:
        page.add_init_script(stealth_script_for_level("aggressive"))
    """
    return generate_stealth_js(get_stealth_preset(level))
