# HDRI Match Plate — Feature Roadmap

> **Goal:** Identify high-impact features that will **boost demand** and differentiate this tool from existing HDRI editing solutions (HDR Light Studio, HDRI Haven tools, Nuke's native workflow, etc.)

---

## What You Already Have (Strengths)

| Feature | Status |
|---|---|
| HDRI ↔ Plate exposure & WB matching | ✅ Complete |
| Multi-mask region grading (Rect, Ellipse, Polygon, Lasso, Brush) | ✅ Complete |
| Macbeth / Chrome / Grey Ball calibration | ✅ Complete |
| Horizon / hemisphere separation | ✅ Complete |
| Soft-clip highlight compression | ✅ Complete |
| CG light AOV matching (Arnold multi-pass) | ✅ Complete |
| Sun detection & extraction | ✅ Complete |
| Nuke node export | ✅ Complete |
| Houdini OBJ / Solaris USD light export | ✅ Complete |
| Camera metadata extraction → Solaris | ✅ Complete |
| Lookdev balls USD generation | ✅ Complete |
| RGB Parade / Luma waveform scopes | ✅ Complete |
| False color / clipping analysis | ✅ Complete |
| Save/Load project state | ✅ Complete |
| ACEScg / OCIO-managed pipeline | ✅ Complete |

---

## 🔴 Tier 1 — Highest Demand (Broadest Audience)

These features target the **widest possible user base** — lighters, compositors, lookdev TDs, and supervision — and would generate the most buzz on LinkedIn, forums, and in studio adoption.

---

### 1. 🌞 Interactive HDRI Sun Relighting (✅ COMPLETED)

**What:** Let users click a point on the HDRI to define the sun position, then interactively drag it to a new position. The tool would warp the sun disc, recalculate the distant light vector, and update the grading to simulate a different time of day.

**Why this is a killer feature:**
- HDR Light Studio charges $800+/seat for this exact capability
- Every lighter has been asked "can we move the sun 15 degrees left?"
- No free/open-source tool does this properly in scene-linear ACEScg

---

### 2. 🎨 Real-Time CG Over Plate Composite Viewer

**What:** Load a CG render (already supported) and the plate, and show a **real-time composite** with contact shadows and holdout mattes. This turns the tool from "HDRI prep" into a **lookdev verification station**.

**Why:**
- Compositors currently switch to Nuke to verify their HDRI calibration
- A built-in comp preview with adjustable CG-over-plate is a massive time saver
- Studios doing lookdev rounds need this loop to be instant

**What's missing (you already have most of this):**
- ✅ CG beauty + alpha loading
- ✅ CG-over-plate view mode
- 🚫 Contact shadow estimation (Disabled by request)
- ✅ Ground plane shadow catch / reflection pass integration
- ✅ A/B wipe between original plate and CG composite ('W' hotkey interactive swipe)

---

### 3. 📊 HDRI Statistics / QC Report Panel (✅ COMPLETED)

**What:** A one-click panel that generates a professional QC report:
- Dynamic range (min/max EV, stops of latitude)
- Sun position (azimuth, elevation in degrees)
- Dominant illuminant CCT (correlated color temperature in Kelvin)
- Coverage analysis (% sky, % ground, % overexposed, % underexposed)
- Resolution and aspect ratio
- Suggested render settings (light samples, shadow resolution)

**Why:**
- VFX Supervisors and lighting leads **always** ask for this metadata
- On-set HDRI capture teams need quick validation before wrap
- No tool auto-generates a professional HDRI spec sheet

---

### 4. 🔄 Batch Processing Mode (✅ COMPLETED)

**What:** Queue up multiple HDRI + Plate pairs and process them all with the same (or per-shot) calibration settings. Export calibrated HDRIs, Nuke scripts, and Solaris packages in bulk.

**Why:**
- Any show with more than 5 shots has 5+ HDRIs to calibrate
- Batch is the difference between "cool personal tool" and "studio pipeline tool"
- Studios will adopt if it saves their lighting team 30 min/shot × 50 shots

**Implementation:**
- CSV/JSON manifest: `[{hdri: path, plate: path, overrides: {...}}, ...]`
- Reuse `CalibrationPipeline` in headless mode (it's already decoupled from UI)
- Progress bar + log output

---

### 5. 🌐 Blender / Unreal Export (✅ COMPLETED)

**What:** Add export targets for Blender (Python scene setup) and Unreal Engine (DataTable JSON + Blueprint-compatible light data).

**Why:**
- Blender has the largest and fastest-growing 3D user base
- Unreal is increasingly used in VFX (virtual production, previs)
- Your Houdini export is excellent — replicating it for Blender/Unreal triples your audience

---

## 🟡 Tier 2 — Power-User Differentiators

These appeal to senior TDs, pipeline architects, and studios evaluating tools.

---

### 6. 🧠 AI-Powered Auto White Balance (Completed)

**What:** Instead of gray-world estimation, use a lightweight ML model to estimate scene illuminant from the plate image. This handles challenging scenarios (sunset, mixed lighting, neon signs) where gray-world fails.

**Why:**
- Gray-world fails on 30-40% of real-world plates (single-color dominant scenes)
- Even a simple CNN (AWBNet or similar) dramatically improves accuracy
- Marketing gold: "AI-powered calibration"

**Implementation:**
- ONNX runtime inference (single forward pass, <50ms)
- Fallback to gray-world if ONNX not available
- Train or fine-tune on public WB datasets

---

### 7. 🔍 HDRI Backplate Extraction (Completed)

**What:** Automatically extract and export a clean backplate from the HDRI for use as a comp background. Includes:
- Automatic horizon detection and crop
- Perspective correction for ground-level viewing angle
- Resolution upscale for the visible portion
- Separate sky and ground layer export

**Why:**
- Many shots use the HDRI's visible portion as the background plate
- Currently this is a manual Photoshop/Nuke process
- Auto-extraction + perspective correction is a unique selling point

**Implementation Notes:**
- Added a dedicated "Extract HDRI Backplate to Nuke" button in the Export tab.
- Pops up a dialog to let the user select the desired Camera FOV and output resolution (HD, 4K, etc).
- Generates a non-destructive Nuke script using `SphericalTransform` to handle rectilinear mapping.
- Bypasses double-rotation issues by utilizing the existing yaw expression and zeroing pan.
- Retains full access to `N_Sky` and `N_Ground` nodes for separated layer rendering.

---

### 8. 📷 On-Set HDRI Validation (Mobile-Friendly Report)

**What:** Generate an HTML report (self-contained, no dependencies) that can be opened on a tablet or phone for on-set review. Shows:
- HDRI thumbnail with false color overlay
- Sun direction arrow on the panorama
- Plate vs. calibrated HDRI side-by-side
- Key metadata (CCT, EV, sun angle)

**Why:**
- On-set supervisors need quick HDRI validation before the crew moves on
- HTML reports work on any device, no software install needed
- Production-ready QC deliverable

---

### 9. 🎭 Multi-Renderer AOV Support (✅ COMPLETED)

**What:** Extend the CG light match tab beyond Arnold prefixes to auto-detect AOV naming conventions for:
- V-Ray (`VRayLightSelect_*`)
- RenderMan (`lpe:C<L.'lightname'>.*`)
- Redshift (`rsLightGroup_*`)
- Karma/Solaris (`C_Light_*` already supported)

**Why:**
- Opens the tool to non-Arnold studios (the majority of the market)
- V-Ray and Redshift users are the largest segments after Arnold

---

### 10. 🎬 Sequence/Animation Support (✅ COMPLETED)

**What:** Support time-varying HDRI sequences (e.g., sunset transitions captured as EXR sequences) and plate sequences. Show a timeline scrubber and export per-frame calibrated HDRIs.

**Why:**
- Moving shots need per-frame HDRI calibration
- Virtual production shoots often capture HDRI sequences
- This is a premium feature that no free tool offers

---

## 🟢 Tier 3 — Pipeline / Studio-Scale

---

### 11. 🔗 ShotGrid / ftrack Integration

**What:** Publish calibrated HDRIs and light data directly to a production tracking system. Pull shot context (camera lens data, shooting conditions) from ShotGrid/ftrack to auto-configure settings.

**Why:** Studios won't adopt a tool that lives outside their pipeline.

---

### 12. 🖥️ Standalone Executable Distribution (✅ COMPLETED)

**What:** Package as a self-contained `.exe` (PyInstaller/Nuitka) with bundled OCIO configs, so it runs without Python installation outside of Nuke.

**Why:**
- Massively lowers the barrier to adoption
- On-set teams and freelancers don't have Nuke everywhere
- Can be distributed as a free community tool

---

### 13. [x] 🔌 Nuke Panel Mode (Dockable)

**What:** Run as a dockable panel inside Nuke (not just as a standalone window) with live node graph connection. Changes in the panel instantly update a linked Grade/ColorMatrix node in the comp.

**Why:**
- Compositors live in Nuke — a docked panel is 10× more convenient
- Live node graph connection eliminates the export→import round-trip

---

## 🟣 Tier 4 — Generative AI & Advanced ML

---

### 14. 🎨 AI Generative Inpainting (✅ COMPLETED)

**What:** Integrate text-to-image inpainting (via Stable Diffusion, Flux, or a local ComfyUI API bridge) allowing users to draw a mask over crew, light stands, or unwanted clouds in the HDRI and type a prompt (e.g., "clear blue sky", "empty dirt road") to seamlessly hallucinate new environment data.

**Why:**
- HDRI clean-up (removing crew/rigs) is currently a tedious manual clone-stamping process in Nuke or Photoshop.
- Text-driven inpainting directly in 32-bit linear space drastically accelerates set extension and environment cleanup.
- Massive wow-factor feature that sets the tool apart from any existing DCC.
- **Requirement:** For full automatic background removal functionality, users must install the `ComfyUI-rembg` custom node via the ComfyUI Manager.
- **Image Decal (Img2Img):** You can now load reference images (with alpha channels) directly onto the HDRI via the `Image` mask shape. If you pass this into the AI Inpaint module, it will act as an Image-to-Image reference, allowing the AI to integrate your reference image perfectly into the HDRI's lighting via the `Denoise` slider.
