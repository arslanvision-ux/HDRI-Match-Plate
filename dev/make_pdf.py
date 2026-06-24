from fpdf import FPDF
import os

class PDF(FPDF):
    def header(self):
        self.set_font("helvetica", "B", 12)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, "HDRI Match Plate - Professional Documentation", border=False, align="R")
        # For fpdf2 we need to move to the next line manually if we don't use new_x/new_y or ln
        self.set_y(self.get_y() + 15)

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def chapter_title(self, title):
        self.set_font("helvetica", "B", 18)
        self.set_text_color(40, 40, 40)
        self.cell(0, 10, title, align="L")
        self.set_y(self.get_y() + 10)
        self.set_y(self.get_y() + 5)

    def chapter_body(self, body):
        self.set_font("helvetica", "", 11)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 6, body)
        self.set_y(self.get_y() + 5)
        
    def add_image(self, img_path, img_w=180):
        if os.path.exists(img_path):
            # Center the image horizontally based on A4 width (210)
            x_pos = (210 - img_w) / 2
            self.image(img_path, x=x_pos, w=img_w)
            self.set_y(self.get_y() + 10)

pdf = PDF()
pdf.set_auto_page_break(auto=True, margin=15)

pdf.add_page()
# Title Page
pdf.set_y(50)
pdf.set_font("helvetica", "B", 26)
pdf.cell(0, 20, "HDRI Match Plate", align="C")
pdf.set_y(pdf.get_y() + 20)
pdf.set_font("helvetica", "I", 14)
pdf.cell(0, 10, "Technical Documentation & Workflow Guide", align="C")
pdf.set_y(pdf.get_y() + 30)

pdf.set_font("helvetica", "", 12)
pdf.set_text_color(60, 60, 60)
summary = (
    "Executive Summary\n\n"
    "HDRI Match Plate is a cutting-edge pipeline utility built for high-end VFX productions. "
    "It bridges the gap between on-set data acquisition, lighting, and compositing by providing a robust, "
    "mathematically accurate environment to match 360-degree HDR maps and CG renders to live-action reference plates.\n\n"
    "Key Capabilities:\n"
    "- Physically Accurate Calibration: Align HDRIs to match plates using precise EV (Exposure Value), Temperature, and Tint offsets in an ACEScg-compliant linear workspace.\n"
    "- Automated Macbeth Chart Analysis: Automatically detect ColorChecker charts in reference plates to calculate exact white-balance and exposure shifts.\n"
    "- Hemisphere Separation: Isolate sky ambient fill and ground bounce light with distinct grading controls and soft-clipping for extreme highlights.\n"
    "- CG Multi-Pass Interactive Compositing: Load multi-pass EXR renders (Arnold, V-Ray, Karma) to interactively dial in light group intensities and colors directly against the plate.\n"
    "- Generative AI Inpainting: Leverage a ComfyUI integration to seamlessly paint out rigs, tripods, and crew members using distortion-free spherical projections.\n"
    "- Seamless DCC Integration: Export node graphs directly into Foundry Nuke via a one-click clipboard operation, or run as a live-linked docked panel inside Nuke for real-time synchronization. Export light multiplier scripts to Houdini and Blender."
)
pdf.multi_cell(0, 6, summary)
pdf.set_y(pdf.get_y() + 10)

base_dir = "E:/PROJECTS/HDRI_Match_Plate/hdri_match/screenshots/"

# 1. Calibration
pdf.add_page()
pdf.chapter_title("1. Introduction & Overview")
pdf.chapter_body("HDRI Match Plate is designed for professional VFX compositing and lighting workflows. It allows TDs and artists to seamlessly align, color-calibrate, and export HDRI environment maps and CG light multi-passes to perfectly match on-set photographic plates.\n\n"
"Deployment Modes:\n"
"- Standalone Application: Run the tool entirely outside of any DCC via the provided executable. Perfect for lighting TDs or onset data wranglers preparing HDRIs before a sequence starts.\n"
"- Nuke Docked Panel: Natively integrates directly into Foundry Nuke as a docked UI panel. This allows for live-link synchronization, where adjusting a slider in the panel instantly updates the live ScanlineRender node graph inside your Nuke script.\n\n"
"The HDRI Calibration tab allows precise alignment of the 360 environment map against the reference plate.\n\n"
"Parameters:\n"
"- Global Exposure & Color: Yaw rotation, EV Offset, Temperature, and Tint.\n"
"- Hemisphere Separation: Isolate sky and ground lighting.\n"
"- Highlight Compression: Logarithmic roll-off for extreme values.")
pdf.add_image(os.path.join(base_dir, "callibration.jpg"))

# 2. Macbeth Auto Crop
pdf.add_page()
pdf.chapter_title("2. Macbeth Auto Crop & Calibrate")
pdf.chapter_body("Automated workflow for Macbeth chart analysis and color calibration.\n\n"
"Features:\n"
"- Auto-detects the ColorChecker chart in the reference plate.\n"
"- Extracts neutral patches to calculate precise white balance.\n"
"- Automatically calibrates the HDRI to match the chart's exposure and temperature.")
pdf.add_image(os.path.join(base_dir, "Macbeth_Auto_Crop_Callibrate.jpg"))

# 3. CG Lookdev
pdf.add_page()
pdf.chapter_title("3. CG Lookdev Match")
pdf.chapter_body("The CG Lookdev Match tab acts as an interactive compositing environment for matching CG light passes to the physical plate.\n\n"
"Render Engine & AOV Flexibility:\n"
"- Multi-Engine Support: The tool seamlessly supports multi-channel EXRs generated from any modern path-tracer (Arnold, V-Ray, Karma, Redshift, Octane, Renderman). As long as the passes are stored linearly inside the EXR, they can be calibrated.\n"
"- Custom AOV Prefixes: Instead of relying on hardcoded channel names, you can input your own AOV prefixes (e.g., 'lgt_', 'CGLight_', 'crypto_'). This allows the tool to automatically parse and group the correct light channels regardless of your studio's specific pipeline naming conventions.\n\n"
"Interactive Light Tweaking:\n"
"- Light Group Sliders: Dynamically tweak the intensity (EV) and color (Temp/Tint) of individual light passes or light filters directly against the live-action plate. This acts as a real-time pre-comp before jumping into Nuke.\n"
"- Solo, Reset, and Sample Color: Isolate specific lights to see their contribution, or use the color-picker to sample light color directly from the reference plate and apply it to a CG light pass.\n"
"- Composite Options: Dial in the Reflection Intensity and CG Opacity Mix to refine how shadow catchers and reflections blend onto the real-world geometry.")
pdf.add_image(os.path.join(base_dir, "lookdev.jpg"))

# 4. Parameters
pdf.add_page()
pdf.chapter_title("4. Parameters & Viewport Properties")
pdf.chapter_body("The Parameters tab provides granular control over the physical exposure of the HDRI dome and viewer interaction settings.\n\n"
"Global Exposure:\n"
"- Dome EV: Adjusts the raw exposure multiplier of the HDRI texture. This is crucial for matching the physical brightness of the environment map to the camera plate before applying artistic grades or soft-clipping.\n"
"- Irradiance Tracking: The UI automatically tracks the average irradiance of the dome to physically tint ambient reflections based on the core exposure setting.")
pdf.add_image(os.path.join(base_dir, "Parameters.jpg"), img_w=140)

# 5. Inpainting AI
pdf.add_page()
pdf.chapter_title("5. Generative Inpainting AI")
pdf.chapter_body("HDRI Match Plate integrates deeply with AI generative models via a ComfyUI backend, allowing you to seamlessly remove rigs, crew members, or unwanted artifacts from your 360 HDR maps.\n\n"
"Core Features & Workflow:\n"
"- Multi-Layer Masking: Create, name, and reorder masks using standard blending modes (Over, Plus, Multiply). You can paint masks manually or use translation, scale, and rotation controls to position shapes precisely.\n"
"- Spherical Projection: A critical feature that transforms the equirectangular map into an undistorted projection before AI generation. This prevents the AI from generating pinched or warped textures near the poles.\n"
"- Use Custom API JSON: An advanced feature allowing you to bypass the built-in architectures. By enabling this checkbox, you can load your own exported ComfyUI workflows (.json). The tool will automatically inject the current HDRI and Mask into your custom workflow, giving you limitless control over the node graph.\n"
"- Custom Model Overrides: While the tool provides quick presets (like SDXL or Flux), you can use the folder icons to load your own UNET, VAE, and CLIP models directly from your file system. This allows studios to use fine-tuned or proprietary diffusion models.\n"
"- Prompt Configuration: Enter positive and negative prompts to guide the AI's generation. The AI relies on these prompts alongside context-awareness to naturally patch the HDRI.")
pdf.add_image(os.path.join(base_dir, "InpaintingAI.jpg"))

# 6. Export
pdf.add_page()
pdf.chapter_title("6. Export Pipeline")
pdf.chapter_body("Generate production-ready setups for 3D and Compositing packages.\n\n"
"Features:\n"
"- Export Nuke Setup: Automatically generates connected node graphs (Read, Scene, ScanlineRender).\n"
"- Export CG Light Multipliers: Generates scripts for Houdini and Blender.\n"
"- Live Link synchronization.")
pdf.add_image(os.path.join(base_dir, "Export.jpg"))

# 7. Sequence Animation Export
pdf.add_page()
pdf.chapter_title("7. Sequence Animation & Rendering")
pdf.chapter_body("HDRI Match Plate is not limited to static images - it fully supports animated sequences and moving plates, allowing for dynamic lighting extraction and sequence rendering over time.\n\n"
"Animation Features:\n"
"- Moving Plate Sequences: Load animated image sequences (EXR, JPG, PNG) as your reference plate. The timeline controls at the bottom of the UI allow you to scrub through the shot frame-by-frame.\n"
"- Frame-by-Frame Calibration: Track changing light conditions across a sequence. As the sun moves or clouds pass by in the plate, you can dynamically align the HDRI.\n"
"- Sequence Exporting: When exporting to Nuke, the generated script automatically detects the frame range of your plate sequence and configures the 'Read' nodes to load the full animation range.\n"
"- Time-Offset & Sync: If your HDRI is also an animated sequence (e.g., a time-lapse dome), the tool ensures the frame synchronization is preserved when pushed into the DCC pipeline.")

# 8. Installation
pdf.add_page()
pdf.chapter_title("8. Installation & Setup")
pdf.chapter_body("HDRI Match Plate can be deployed in three different ways: as a Standalone Application, a Nuke Floating Window, or a Nuke Docked Panel.\n\n"
"1. Standalone Application Installation:\n"
"- No complex setup is required. Extract the provided 'HDRI_Match_Plate_Standalone' folder to your desired location.\n"
"- Double-click 'Run_Standalone.bat' (Windows) or the application executable to launch the tool.\n"
"- Dependencies: The standalone package comes with a bundled Python environment. If running from source, install requirements via: 'pip install PySide6 opencv-python colour-science numpy'.\n\n"
"2. Nuke Floating Window (Menu Integration):\n"
"- Copy the entire 'hdri_match' package, along with 'init.py' and 'menu.py', into your '.nuke' folder, or a directory on your 'NUKE_PATH'.\n"
"- Restart Nuke. The tool will be available via the top menu bar under 'HDRI Tools -> Match Plate Calibration'.\n"
"- This runs the tool as an independent, floating PySide window while keeping access to Nuke's Python environment.\n\n"
"3. Nuke Docked Panel Installation:\n"
"- Copy the 'hdri_match' python package directory into your '.nuke' folder.\n"
"- Open your '.nuke/menu.py' file in a text editor.\n"
"- Add the following code to register the dockable panel:\n"
"      import nuke\n"
"      import hdri_match.nuke_panel\n"
"      hdri_match.nuke_panel.register_panel()\n"
"- Restart Nuke. You can now open the tool natively docked in your UI by navigating to the 'Windows -> Custom Panels -> HDRI Match Plate' menu.\n"
"- This mode supports the 'Live Link' feature, automatically updating the node graph as you adjust sliders.")

pdf.output("e:/PROJECTS/HDRI_Match_Plate/HDRI_Match_Plate_Tutorial.pdf")
