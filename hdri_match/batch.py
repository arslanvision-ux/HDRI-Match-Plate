import os
import sys
import json
import argparse
from pathlib import Path

from hdri_match.core.pipeline import CalibrationPipeline
from hdri_match.io.exporter import save_numpy_to_image
from hdri_match.io.nuke_export import export_nuke_nodes

def process_batch(manifest_path: str):
    """
    Process a list of shots defined in a JSON manifest file.
    Manifest format:
    [
        {
            "project": "path/to/project.json",
            "hdri": "override/path/to/hdri.exr", 
            "plate": "override/path/to/plate.exr", 
            "output_dir": "path/to/output_dir",
            "export_nuke": true,
            "export_solaris": false
        }
    ]
    """
    if not os.path.exists(manifest_path):
        print(f"Error: Manifest file not found: {manifest_path}")
        return

    with open(manifest_path, 'r') as f:
        try:
            manifest = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing manifest JSON: {e}")
            return

    if not isinstance(manifest, list):
        print("Error: Manifest must be a JSON array of shot dictionaries.")
        return

    pipeline = CalibrationPipeline()

    print(f"Starting batch processing of {len(manifest)} shots...\n")

    for idx, task in enumerate(manifest):
        print(f"--- Processing Shot {idx + 1}/{len(manifest)} ---")
        
        project_path = task.get("project")
        if not project_path or not os.path.exists(project_path):
            print(f"  [ERROR] Project file missing or invalid: {project_path}")
            continue

        print(f"  Loading project: {project_path}")
        hdri_path, plate_path, cg_exr_path, _ = pipeline.load_project(project_path)

        # Allow manifest overrides for hdri and plate paths
        hdri_path = task.get("hdri", hdri_path)
        plate_path = task.get("plate", plate_path)

        if not hdri_path or not os.path.exists(hdri_path):
            print(f"  [ERROR] HDRI file missing or invalid: {hdri_path}")
            continue

        output_dir = task.get("output_dir")
        if not output_dir:
            print(f"  [ERROR] output_dir not specified in task.")
            continue

        os.makedirs(output_dir, exist_ok=True)

        print(f"  Loading inputs...")
        try:
            # We don't necessarily have a plate if we just want to process an HDRI
            pipeline.load_inputs(hdri_path, plate_path)
        except Exception as e:
            print(f"  [ERROR] Failed to load inputs: {e}")
            continue

        print(f"  Processing HDRI...")
        try:
            pipeline.process_hdri(use_proxy=False)
        except Exception as e:
            print(f"  [ERROR] Failed to process HDRI: {e}")
            continue

        base_name = os.path.splitext(os.path.basename(hdri_path))[0]
        out_exr = os.path.join(output_dir, f"{base_name}_calibrated.exr")

        print(f"  Saving calibrated HDRI to {out_exr}...")
        save_numpy_to_image(pipeline.state.calibrated_hdri, out_exr)

        if task.get("export_nuke", True):
            nuke_script = os.path.join(output_dir, f"{base_name}_comp_setup.nk")
            print(f"  Exporting Nuke script to {nuke_script}...")
            try:
                # Nuke export requires pipeline state
                script_content = export_nuke_nodes(pipeline.state)
                with open(nuke_script, "w") as f:
                    f.write(script_content)
            except Exception as e:
                print(f"  [ERROR] Failed to export Nuke script: {e}")

        if task.get("export_solaris", False):
            from hdri_match.io.solaris_export import export_solaris_usd
            usd_path = os.path.join(output_dir, f"{base_name}_lighting.usda")
            print(f"  Exporting Solaris USD to {usd_path}...")
            try:
                export_solaris_usd(pipeline.state.masks, pipeline.state.calibrated_hdri, output_dir, out_exr)
            except Exception as e:
                print(f"  [ERROR] Failed to export Solaris USD: {e}")

        print("  Shot complete.\n")

    print("Batch processing finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HDRI Match Plate - Batch Processor")
    parser.add_argument("manifest", help="Path to the JSON manifest file")
    args = parser.parse_args()
    process_batch(args.manifest)
