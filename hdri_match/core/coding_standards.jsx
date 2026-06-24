import { useState } from "react";

const SECTIONS = [
  {
    id: "structure",
    icon: "⬡",
    label: "Project Structure",
    color: "#7dd3fc",
    rules: [
      {
        id: "s1",
        title: "Package layout: separate core / io / calibration / ui",
        why: "Keeps domain logic away from I/O and UI. Allows unit-testing pipeline math without a display.",
        good: `hdri_match/
  core/          # data_models.py, colorspace.py
  calibration/   # exposure.py, white_balance.py, sun_detection.py
  io/            # loader.py, exporter.py
  ui/            # main_window.py, panels.py, viewer.py, widgets.py`,
        bad: `hdri_match/
  everything.py  # 2 000 lines mixing Qt, numpy, file I/O`,
        goodLabel: "Your current layout ✓",
        badLabel: "Monolith",
      },
      {
        id: "s2",
        title: "One class per file (for large domain classes)",
        why: "CalibrationPipeline, ImageState, ColorSpaceManager — each deserves its own file so git diffs stay focused.",
        good: `# pipeline.py
class CalibrationPipeline: ...

# data_models.py
@dataclasses.dataclass
class ImageState: ...`,
        bad: `# models.py
class ImageState: ...
class CalibrationPipeline: ...
class ColorSpaceManager: ...
class FalseColorEngine: ...`,
        goodLabel: "Focused file",
        badLabel: "Kitchen-sink file",
      },
      {
        id: "s3",
        title: "Keep UI files thin — no NumPy logic in panels.py or widgets.py",
        why: "If panels.py grows numpy operations it becomes untestable without a display. Push all array work into the pipeline.",
        good: `# panels.py — just calls the pipeline
self.pipeline.compute_calibration(
    use_chrome_ball=self.cb_chrome.isChecked()
)`,
        bad: `# panels.py — numpy leaked into UI layer
luma = np.dot(image[..., :3], [0.2126, 0.7152, 0.0722])
ev = np.log2(np.percentile(luma, 50))`,
        goodLabel: "Thin panel",
        badLabel: "Logic in UI",
      },
    ],
  },
  {
    id: "dataclasses",
    icon: "◈",
    label: "Data Models",
    color: "#86efac",
    rules: [
      {
        id: "d1",
        title: "All ImageState fields must have a default value",
        why: "AttributeError: 'ImageState' object has no attribute 'black_offset' is the exact bug you just fixed. Every field must live in the dataclass with a safe default.",
        good: `@dataclasses.dataclass
class ImageState:
    ev_offset: float = 0.0
    black_offset: float = 0.0   # ← always add here first
    temperature: float = 0.0`,
        bad: `# Defined in pipeline.py instead:
self.state.black_offset = 0.0
# → AttributeError on first access before pipeline runs`,
        goodLabel: "Declared in dataclass ✓",
        badLabel: "Side-assigned later",
      },
      {
        id: "d2",
        title: "Group fields by section with comment headers",
        why: "ImageState has 20+ fields. Section comments (# Raw arrays, # Proxies, # Metadata) make it scannable at a glance.",
        good: `# Raw loaded linear arrays (Full Res)
hdri_array: Optional[np.ndarray] = None
plate_array: Optional[np.ndarray] = None

# Proxies for fast UI interaction (Downsampled)
hdri_proxy: Optional[np.ndarray] = None`,
        bad: `hdri_array: Optional[np.ndarray] = None
hdri_proxy: Optional[np.ndarray] = None
ev_offset: float = 0.0
hdri_path: Optional[str] = None
cg_lights: Optional[dict] = None`,
        goodLabel: "Grouped with headers ✓",
        badLabel: "Unsorted mix",
      },
      {
        id: "d3",
        title: "Use typed dicts or nested dataclasses instead of Optional[dict]",
        why: "cg_light_params: Optional[dict] hides the schema. A TypedDict makes the shape explicit and enables IDE autocomplete.",
        good: `from typing import TypedDict

class LightParams(TypedDict):
    ev: float
    temp: float
    tint: float

cg_light_params: Optional[dict[str, LightParams]] = None`,
        bad: `cg_light_params: Optional[dict] = None
# {"light_key_01": {"ev": 0.0, "temp": 0.0, "tint": 0.0}}
# ← schema lives only in a comment`,
        goodLabel: "Typed schema",
        badLabel: "Comment-only schema",
      },
    ],
  },
  {
    id: "functions",
    icon: "⬟",
    label: "Functions & Methods",
    color: "#fcd34d",
    rules: [
      {
        id: "f1",
        title: "All public methods need a docstring + Args/Returns block",
        why: "Your best methods (estimate_illuminant_gray_world, build_sun_mask) already do this well — apply the same standard everywhere.",
        good: `@staticmethod
def masked_percentile(image: np.ndarray,
                       mask: np.ndarray,
                       percentile: float) -> float:
    """
    Computes luminance percentile using only non-sun pixels.

    Args:
        image:      Float32 RGB array (H, W, 3).
        mask:       Bool array (H, W) — True = safe pixel.
        percentile: Value in [0, 100].
    Returns:
        Scalar luminance at the requested percentile.
    """`,
        bad: `@staticmethod
def masked_percentile(image, mask, percentile):
    # computes percentile
    luma = SunDetector.compute_luminance(image)`,
        goodLabel: "Full docstring ✓",
        badLabel: "No type hints, no docs",
      },
      {
        id: "f2",
        title: "Don't import inside functions unless avoiding a circular import",
        why: "import math and import cv2 buried inside compute_calibration and _create_proxy make dependencies invisible and slow repeated calls.",
        good: `# Top of pipeline.py
import math
try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False`,
        bad: `def compute_calibration(self, ...):
    ...
    import math                 # ← hidden dependency
    self.state.ev_offset = math.log2(scale_factor)

def _create_proxy(self, img, max_dim=1536):
    try:
        import cv2              # ← imported on every call`,
        goodLabel: "Top-level imports ✓",
        badLabel: "Buried imports",
      },
      {
        id: "f3",
        title: "Static utility classes → standalone module-level functions",
        why: "ExposureAnalyzer.apply_exposure is @staticmethod with no state — there's no benefit to the class wrapper. Module functions are simpler to import and test.",
        good: `# exposure.py
def apply_exposure(image: np.ndarray, ev_offset: float) -> np.ndarray:
    """Applies an EV offset to a linear image."""
    return image * (2.0 ** ev_offset)`,
        bad: `class ExposureAnalyzer:
    @staticmethod
    def apply_exposure(image: np.ndarray, ev_offset: float) -> np.ndarray:
        return image * (2.0 ** ev_offset)
# ExposureAnalyzer carries no state — the class adds nothing`,
        goodLabel: "Module function",
        badLabel: "Stateless class wrapper",
      },
    ],
  },
  {
    id: "errors",
    icon: "◉",
    label: "Error Handling",
    color: "#f9a8d4",
    rules: [
      {
        id: "e1",
        title: "Raise specific exceptions with actionable messages",
        why: "Your ValueError in load_cg_lights is a great example. Every raise should tell the user what was expected, not just what failed.",
        good: `if not lights:
    raise ValueError(
        "No AOVs starting with 'light_' found in the EXR.\\n"
        "Expected channels named: light_key_01.R/G/B etc."
    )`,
        bad: `if not lights:
    raise ValueError("No lights found")`,
        goodLabel: "Actionable message ✓",
        badLabel: "Vague message",
      },
      {
        id: "e2",
        title: "Never silence exceptions with bare except: pass",
        why: "Silent failures in image pipelines are the hardest bugs to track. At minimum, log with print(); ideally use logging.warning().",
        good: `try:
    cpu.applyRGB(img_flat)
except AttributeError:
    # Older OCIO versions require RGBA — fall back transparently
    rgba = np.ones((h * w, 4), dtype=np.float32)
    ...`,
        bad: `try:
    result = process_image(arr)
except:
    pass  # ← swallows every error silently`,
        goodLabel: "Documented fallback ✓",
        badLabel: "Silent swallow",
      },
      {
        id: "e3",
        title: "Replace print() with logging for operational messages",
        why: "print('[SunDetector] HDRI sun coverage: 0.02%') works today, but logging lets you filter levels, redirect to files, and disable in production without touching code.",
        good: `import logging
log = logging.getLogger(__name__)

log.info("[SunDetector] HDRI sun coverage: %.2f%%", pct)
log.warning("PyOpenColorIO not found — running in fallback mode.")`,
        bad: `print(f"[SunDetector] HDRI sun coverage: {pct:.2f}%")
print("PyOpenColorIO not found. Running in fallback mode.")`,
        goodLabel: "logging module",
        badLabel: "print() for ops output",
      },
    ],
  },
  {
    id: "numpy",
    icon: "⬢",
    label: "NumPy & Image Arrays",
    color: "#c4b5fd",
    rules: [
      {
        id: "n1",
        title: "Guard against division by zero with np.maximum, not Python max()",
        why: "np.maximum(arr, 1e-8) works element-wise on arrays. Python's max() only works on scalars and will raise on an ndarray.",
        good: `luma_out = np.maximum(luma_out, 1e-8)
luma_ratio = luma_in / luma_out   # safe element-wise`,
        bad: `luma_out = max(luma_out, 1e-8)
# TypeError: the truth value of an array is ambiguous`,
        goodLabel: "np.maximum for arrays ✓",
        badLabel: "Python max() on array",
      },
      {
        id: "n2",
        title: "Always pass dtype=np.float32 when creating arrays for the pipeline",
        why: "Mixing float64 (NumPy default) and float32 (OCIO/OpenCV requirement) causes silent precision bloat and OCIO type errors.",
        good: `illuminant = np.array([r, g, b], dtype=np.float32)
img_flat = np.ascontiguousarray(image, dtype=np.float32)`,
        bad: `illuminant = np.array([r, g, b])        # float64 default
img_flat = image.flatten()             # may be float64`,
        goodLabel: "Explicit float32 ✓",
        badLabel: "Implicit float64",
      },
      {
        id: "n3",
        title: "Use np.clip before log/sqrt to prevent NaN propagation",
        why: "log2(0) = -inf in NumPy and silently contaminates the entire array downstream. Clip early, clip explicitly.",
        good: `luma = np.clip(luma, 1e-8, None)
ev_map = np.log2(luma / 0.18)  # safe`,
        bad: `ev_map = np.log2(luma / 0.18)
# luma=0 pixels → -inf → corrupts downstream normalisation`,
        goodLabel: "Clip before log ✓",
        badLabel: "Unguarded log",
      },
    ],
  },
  {
    id: "optional_deps",
    icon: "◎",
    label: "Optional Dependencies",
    color: "#fdba74",
    rules: [
      {
        id: "o1",
        title: "Wrap optional imports in try/except at module level with a None sentinel",
        why: "Your PyOpenColorIO and cv2 patterns are exactly right. Apply the same pattern to every optional dep (rawpy, imageio, scipy).",
        good: `try:
    import PyOpenColorIO as OCIO
except ImportError:
    OCIO = None

# Later: guard on the sentinel
if OCIO is None:
    return image  # graceful fallback`,
        bad: `# In the middle of a function:
import PyOpenColorIO as OCIO  # crashes at call time
processor = OCIO.Config.CreateFromFile(path)`,
        goodLabel: "Module-level sentinel ✓",
        badLabel: "Inline import, no fallback",
      },
      {
        id: "o2",
        title: "Document required vs optional deps in a requirements file",
        why: "numpy, PySide6 are required. cv2, scipy, rawpy, OpenEXR are optional with defined fallbacks. This should be explicit, not tribal knowledge.",
        good: `# requirements.txt
numpy>=1.24
PySide6>=6.5

# requirements-optional.txt
opencv-python>=4.8     # faster proxy generation + EXR I/O
scipy>=1.11            # faster sun mask dilation
rawpy>=0.18            # RAW file support
PyOpenColorIO>=2.2     # full color management`,
        bad: `# No requirements file — users discover missing
# packages one-by-one at runtime via stack traces`,
        goodLabel: "Documented deps",
        badLabel: "Undocumented optionals",
      },
    ],
  },
];

const CHECK_KEY = "hdri_coding_standards_checks_v1";

function loadChecks() {
  try {
    const raw = window._stdChecks;
    return raw ? JSON.parse(raw) : {};
  } catch { return {}; }
}

function saveChecks(checks) {
  window._stdChecks = JSON.stringify(checks);
}

export default function App() {
  const [checks, setChecks] = useState(loadChecks);
  const [expanded, setExpanded] = useState({});
  const [activeSection, setActiveSection] = useState("structure");
  const [codeView, setCodeView] = useState({});

  const toggle = (id) => {
    const next = { ...checks, [id]: !checks[id] };
    setChecks(next);
    saveChecks(next);
  };

  const toggleExpand = (id) => {
    setExpanded(p => ({ ...p, [id]: !p[id] }));
  };

  const toggleCode = (id) => {
    setCodeView(p => ({ ...p, [id]: p[id] === "good" ? "bad" : "good" }));
  };

  const totalRules = SECTIONS.flatMap(s => s.rules).length;
  const checkedCount = Object.values(checks).filter(Boolean).length;
  const progress = Math.round((checkedCount / totalRules) * 100);

  const activeData = SECTIONS.find(s => s.id === activeSection);

  return (
    <div style={{
      fontFamily: "'IBM Plex Mono', 'Courier New', monospace",
      background: "#0f1117",
      minHeight: "100vh",
      color: "#c9d1d9",
      display: "flex",
      flexDirection: "column",
    }}>
      {/* Header */}
      <div style={{
        borderBottom: "1px solid #21262d",
        padding: "20px 28px 16px",
        background: "#161b22",
      }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, letterSpacing: 3, color: "#58a6ff", textTransform: "uppercase" }}>
            hdri_match
          </span>
          <span style={{ color: "#30363d", fontSize: 13 }}>·</span>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#e6edf3", letterSpacing: -0.5 }}>
            Python Coding Standards
          </h1>
        </div>

        {/* Progress bar */}
        <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            flex: 1, height: 6, background: "#21262d", borderRadius: 3, overflow: "hidden",
            maxWidth: 400,
          }}>
            <div style={{
              height: "100%",
              width: `${progress}%`,
              background: progress === 100
                ? "linear-gradient(90deg, #3fb950, #56d364)"
                : "linear-gradient(90deg, #1f6feb, #58a6ff)",
              borderRadius: 3,
              transition: "width 0.4s ease",
            }} />
          </div>
          <span style={{ fontSize: 11, color: "#8b949e", whiteSpace: "nowrap" }}>
            {checkedCount} / {totalRules} rules reviewed
            {progress === 100 && " 🎉"}
          </span>
        </div>
      </div>

      <div style={{ display: "flex", flex: 1 }}>
        {/* Sidebar */}
        <div style={{
          width: 200,
          borderRight: "1px solid #21262d",
          background: "#161b22",
          padding: "16px 0",
          flexShrink: 0,
        }}>
          {SECTIONS.map(s => {
            const done = s.rules.filter(r => checks[r.id]).length;
            const isActive = s.id === activeSection;
            return (
              <button
                key={s.id}
                onClick={() => setActiveSection(s.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  width: "100%",
                  padding: "10px 18px",
                  background: isActive ? "#21262d" : "transparent",
                  border: "none",
                  borderLeft: isActive ? `3px solid ${s.color}` : "3px solid transparent",
                  color: isActive ? "#e6edf3" : "#8b949e",
                  cursor: "pointer",
                  textAlign: "left",
                  fontSize: 12,
                  transition: "all 0.15s",
                }}
              >
                <span style={{ fontSize: 14, color: s.color, opacity: isActive ? 1 : 0.6 }}>{s.icon}</span>
                <span style={{ flex: 1, lineHeight: 1.3 }}>{s.label}</span>
                <span style={{
                  fontSize: 10,
                  background: done === s.rules.length ? "#1a3a1a" : "#1c2128",
                  color: done === s.rules.length ? "#3fb950" : "#8b949e",
                  borderRadius: 10,
                  padding: "1px 6px",
                  minWidth: 28,
                  textAlign: "center",
                }}>
                  {done}/{s.rules.length}
                </span>
              </button>
            );
          })}
        </div>

        {/* Main content */}
        <div style={{ flex: 1, padding: "24px 28px", overflowY: "auto" }}>
          {/* Section header */}
          <div style={{ marginBottom: 20, display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 22, color: activeData.color }}>{activeData.icon}</span>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#e6edf3" }}>
              {activeData.label}
            </h2>
            <span style={{ fontSize: 11, color: "#8b949e", marginLeft: 4 }}>
              ({activeData.rules.length} rules)
            </span>
          </div>

          {activeData.rules.map((rule) => {
            const isChecked = !!checks[rule.id];
            const isExpanded = !!expanded[rule.id];
            const viewMode = codeView[rule.id] || "good";

            return (
              <div key={rule.id} style={{
                marginBottom: 14,
                border: `1px solid ${isChecked ? "#238636" : "#21262d"}`,
                borderRadius: 8,
                overflow: "hidden",
                background: isChecked ? "#0d1f10" : "#161b22",
                transition: "all 0.2s",
              }}>
                {/* Rule header row */}
                <div style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 12,
                  padding: "14px 16px",
                  cursor: "pointer",
                }} onClick={() => toggleExpand(rule.id)}>

                  {/* Checkbox */}
                  <div
                    onClick={e => { e.stopPropagation(); toggle(rule.id); }}
                    style={{
                      width: 18, height: 18, borderRadius: 4,
                      border: `2px solid ${isChecked ? "#3fb950" : "#30363d"}`,
                      background: isChecked ? "#238636" : "transparent",
                      flexShrink: 0,
                      marginTop: 1,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      cursor: "pointer",
                      transition: "all 0.15s",
                    }}
                  >
                    {isChecked && (
                      <svg width="10" height="8" viewBox="0 0 10 8">
                        <path d="M1 4l3 3 5-6" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    )}
                  </div>

                  <div style={{ flex: 1 }}>
                    <div style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: isChecked ? "#7ee787" : "#e6edf3",
                      lineHeight: 1.4,
                      textDecoration: isChecked ? "line-through" : "none",
                      opacity: isChecked ? 0.7 : 1,
                    }}>
                      {rule.title}
                    </div>
                  </div>

                  <span style={{
                    fontSize: 11, color: "#8b949e",
                    marginTop: 2, transform: isExpanded ? "rotate(180deg)" : "none",
                    transition: "transform 0.2s",
                  }}>▾</span>
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div style={{ borderTop: "1px solid #21262d", padding: "14px 16px 16px" }}>
                    {/* Why */}
                    <div style={{
                      fontSize: 12, color: "#8b949e", lineHeight: 1.6,
                      marginBottom: 14,
                      padding: "8px 12px",
                      background: "#0d1117",
                      borderRadius: 6,
                      borderLeft: `3px solid ${activeData.color}`,
                    }}>
                      <span style={{ color: activeData.color, fontWeight: 700 }}>Why: </span>
                      {rule.why}
                    </div>

                    {/* Toggle good/bad */}
                    <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                      {["good", "bad"].map(mode => (
                        <button
                          key={mode}
                          onClick={() => setCodeView(p => ({ ...p, [rule.id]: mode }))}
                          style={{
                            padding: "4px 12px",
                            fontSize: 11,
                            borderRadius: 4,
                            border: "1px solid",
                            cursor: "pointer",
                            fontFamily: "inherit",
                            borderColor: viewMode === mode
                              ? (mode === "good" ? "#3fb950" : "#f85149")
                              : "#30363d",
                            background: viewMode === mode
                              ? (mode === "good" ? "#0d2011" : "#1e0b0a")
                              : "transparent",
                            color: viewMode === mode
                              ? (mode === "good" ? "#3fb950" : "#f85149")
                              : "#8b949e",
                          }}
                        >
                          {mode === "good" ? `✓ ${rule.goodLabel}` : `✗ ${rule.badLabel}`}
                        </button>
                      ))}
                    </div>

                    {/* Code block */}
                    <pre style={{
                      margin: 0,
                      padding: "12px 14px",
                      background: "#0d1117",
                      border: `1px solid ${viewMode === "good" ? "#1a3a1a" : "#3a1a1a"}`,
                      borderRadius: 6,
                      fontSize: 11,
                      lineHeight: 1.65,
                      overflowX: "auto",
                      color: viewMode === "good" ? "#7ee787" : "#ffa198",
                      whiteSpace: "pre",
                    }}>
                      {viewMode === "good" ? rule.good : rule.bad}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer */}
      <div style={{
        borderTop: "1px solid #21262d",
        padding: "10px 28px",
        background: "#161b22",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        fontSize: 11,
        color: "#8b949e",
      }}>
        <span>Click any rule to expand · Check off rules as you apply them</span>
        <span style={{ color: "#30363d" }}>hdri_match · Python 3.10+</span>
      </div>
    </div>
  );
}
