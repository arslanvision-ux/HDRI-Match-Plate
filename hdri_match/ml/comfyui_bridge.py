import json
import urllib.request
import urllib.parse
import numpy as np
import os

# Enable OpenEXR support in OpenCV (Required for cv2.imdecode with EXR)
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

class ComfyUIBridge:
    def __init__(self, api_url="http://127.0.0.1:8188", backend="ComfyUI (Local)"):
        self.api_url = api_url.rstrip("/")
        self.backend = backend
        
    def generate_inpaint(self, hdri_array, mask_array, prompt, neg_prompt="bad quality", ckpt="v1-5-pruned-emaonly.safetensors", steps=20, cfg=8.0, unet="", clip="", vae="", rembg=False, denoise=1.0, profile="Auto-Detect", custom_wf_path="", seed=0, upscaler="None"):
        """
        Takes a 32-bit linear EXR array, tonemaps to 8-bit, sends to ComfyUI for inpainting,
        and returns the inpainted patch blended back into 32-bit linear space.
        
        Note: This is a robust framework/skeleton for a production ComfyUI backend.
        Since ComfyUI workflows depend on installed custom nodes, this acts as a placeholder
        that simulates the API request and returns a safe fallback if ComfyUI isn't running.
        """
        try:
            # --- Typical ComfyUI Inpainting Flow ---
            # 2. Tonemap hdri_array (linear) to 8-bit sRGB
            # 3. Convert arrays to PNG bytes
            # 4. Upload image and mask via POST to /upload/image
            # 5. Load workflow.json (LoadImage -> VAEEncodeForInpaint -> KSampler -> VAEDecode -> SaveImage)
            # 6. Inject prompt, image filename, mask filename into JSON
            # 7. POST to /prompt
            # 8. Poll WebSocket or /history for completion
            # 9. GET from /view
            # 10. Decode PNG bytes to numpy array
            # 11. Inverse-tonemap (sRGB 8-bit) -> Linear 32-bit
            # 12. Blend back using the mask
            
            print(f"[{self.backend}] Connecting to {self.api_url}...")
            print(f"[{self.backend}] Inpainting prompt: '{prompt}'")
            
            # --- Dynamic Resolution Scaling ---
            import math
            import cv2
            orig_h, orig_w = hdri_array.shape[:2]
            max_area = 1024 * 1024
            
            if "flux" in str(ckpt).lower() or "flux" in str(unet).lower():
                max_area = 1280 * 1280
                
            scaled_hdri = hdri_array
            scaled_mask = mask_array
            
            needs_scaling = orig_w * orig_h > max_area
            if needs_scaling:
                scale = math.sqrt(max_area / (orig_w * orig_h))
                target_w = (int(orig_w * scale) // 8) * 8
                target_h = (int(orig_h * scale) // 8) * 8
                
                if target_w >= 64 and target_h >= 64:
                    scaled_hdri = cv2.resize(hdri_array, (target_w, target_h), interpolation=cv2.INTER_AREA)
                    scaled_mask = cv2.resize(mask_array, (target_w, target_h), interpolation=cv2.INTER_AREA)
                    print(f"[{self.backend}] Downscaled input from {orig_w}x{orig_h} to {target_w}x{target_h} to maintain relative scale.")
            
            
            # --- API Specific Implementations ---
            if "HuggingFace" in self.backend:
                import cv2
                import base64
                
                img_u8 = (np.clip(scaled_hdri, 0, 1) * 255).astype(np.uint8)
                mask_u8 = (np.clip(scaled_mask, 0, 1) * 255).astype(np.uint8)
                _, img_png = cv2.imencode('.png', cv2.cvtColor(img_u8, cv2.COLOR_RGB2BGR))
                _, mask_png = cv2.imencode('.png', mask_u8)
                
                payload = {
                    "inputs": prompt,
                    "image": base64.b64encode(img_png).decode('utf-8'),
                    "mask_image": base64.b64encode(mask_png).decode('utf-8')
                }
                
                req = urllib.request.Request(
                    "https://router.huggingface.co/hf-inference/models/runwayml/stable-diffusion-inpainting",
                    data=json.dumps(payload).encode('utf-8')
                )
                req.add_header('Authorization', f'Bearer {self.api_url}')
                req.add_header('Content-Type', 'application/json')
                
                try:
                    with urllib.request.urlopen(req) as response:
                        content_type = response.info().get('Content-Type', '')
                        if 'image' in content_type:
                            img_data = response.read()
                            nparr = np.frombuffer(img_data, np.uint8)
                            img_out = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if img_out is not None:
                                print(f"[{self.backend}] Inference successful!")
                                return cv2.cvtColor(img_out, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0, None
                        else:
                            resp_json = json.loads(response.read())
                            print(f"[{self.backend}] API returned JSON instead of image: {resp_json}")
                            return hdri_array.copy(), str(resp_json)
                except urllib.error.HTTPError as e:
                    err_msg = e.read().decode('utf-8', errors='ignore')
                    print(f"[{self.backend}] HTTP Error {e.code}: {err_msg}")
                    return hdri_array.copy(), f"HuggingFace HTTP Error {e.code}:\n{err_msg}"
                except Exception as e:
                    print(f"[{self.backend}] Request failed: {e}")
                    return hdri_array.copy(), f"HuggingFace API Request Failed:\n{e}"
                
            elif "Banana.dev" in self.backend:
                import cv2
                import base64
                
                # 1. Convert to sRGB and base64
                srgb_array = np.clip(scaled_hdri, 0, 1) ** (1.0 / 2.2)
                img_u8 = (srgb_array * 255).astype(np.uint8)
                mask_u8 = (np.clip(scaled_mask, 0, 1) * 255).astype(np.uint8)
                _, img_png = cv2.imencode('.png', cv2.cvtColor(img_u8, cv2.COLOR_RGB2BGR))
                _, mask_png = cv2.imencode('.png', mask_u8)
                
                img_b64 = base64.b64encode(img_png).decode('utf-8')
                mask_b64 = base64.b64encode(mask_png).decode('utf-8')
                
                # Banana v4 payload pattern
                payload = {
                    "modelInputs": {
                        "prompt": prompt,
                        "imageBase64": img_b64,
                        "maskBase64": mask_b64,
                        "num_inference_steps": 20,
                        "guidance_scale": 7.5
                    }
                }
                
                req = urllib.request.Request(
                    "https://api.banana.dev/start/v4/", 
                    data=json.dumps(payload).encode('utf-8')
                )
                # The api_url field acts as the API key in the UI when Cloud is selected
                req.add_header('Authorization', f'Bearer {self.api_url}')
                req.add_header('Content-Type', 'application/json')
                
                try:
                    with urllib.request.urlopen(req) as response:
                        res_json = json.loads(response.read())
                        if "modelOutputs" in res_json and len(res_json["modelOutputs"]) > 0:
                            output_b64 = res_json["modelOutputs"][0].get("imageBase64", "")
                            if output_b64:
                                img_data = base64.b64decode(output_b64)
                                nparr = np.frombuffer(img_data, np.uint8)
                                img_out = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
                                if img_out is not None:
                                    if img_out.ndim == 3 and img_out.shape[-1] == 4:
                                        rgba_out = cv2.cvtColor(img_out, cv2.COLOR_BGRA2RGBA).astype(np.float32) / 255.0
                                        linear_out = np.concatenate([rgba_out[..., :3] ** 2.2, rgba_out[..., 3:4]], axis=-1)
                                    else:
                                        rgb_out = cv2.cvtColor(img_out, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                                        linear_out = rgb_out ** 2.2
                                    req_h, req_w = hdri_array.shape[:2]
                                    if linear_out.shape[:2] != (req_h, req_w):
                                        linear_out = cv2.resize(linear_out, (req_w, req_h), interpolation=cv2.INTER_LANCZOS4)
                                    return linear_out, None
                        return hdri_array.copy(), "Banana API returned empty output."
                except urllib.error.HTTPError as e:
                    return hdri_array.copy(), f"Banana.dev HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')}"
                except Exception as e:
                    return hdri_array.copy(), f"Banana.dev Connection Error: {str(e)}"
                return hdri_array.copy(), "Replicate API not yet implemented."
            elif "Stability" in self.backend:
                return hdri_array.copy(), "Stability API not yet implemented."
            elif "OpenAI" in self.backend:
                return hdri_array.copy(), "OpenAI API not yet implemented."
            else:
                # --- Actual Local ComfyUI Workflow ---
                import cv2
                
                # 0. Ping the server to see if it's alive
                if not self.api_url.startswith("http"):
                    return hdri_array.copy(), "Invalid ComfyUI URL. Must start with http:// or https://"
                req = urllib.request.Request(f"{self.api_url}/system_stats")
                urllib.request.urlopen(req, timeout=1.0)
                # 1. Convert linear to sRGB for AI model
                srgb_array = np.clip(scaled_hdri, 0, 1) ** (1.0 / 2.2)
                img_u8 = (srgb_array * 255).astype(np.uint8)
                mask_u8 = (np.clip(scaled_mask, 0, 1) * 255).astype(np.uint8)
                _, img_png = cv2.imencode('.png', cv2.cvtColor(img_u8, cv2.COLOR_RGB2BGR))
                _, mask_png = cv2.imencode('.png', mask_u8)
                
                # 2. Upload to ComfyUI
                img_filename = self._upload_image(img_png.tobytes(), "hdri_inpaint_target.png")
                mask_filename = self._upload_image(mask_png.tobytes(), "hdri_inpaint_mask.png")
                
                if img_filename and mask_filename:
                    print(f"[{self.backend}] Uploaded {img_filename} and {mask_filename}")
                    if custom_wf_path and os.path.exists(custom_wf_path):
                        with open(custom_wf_path, 'r') as f:
                            custom_wf = json.load(f)
                        import math
                        w = hdri_array.shape[1]
                        h = hdri_array.shape[0]
                        max_area = 1024 * 1024
                        if w * h > max_area:
                            scale = math.sqrt(max_area / (w * h))
                            w = int(w * scale)
                            h = int(h * scale)
                        target_w = (max(64, w) // 8) * 8
                        target_h = (max(64, h) // 8) * 8
                        workflow = self._build_custom_workflow(custom_wf, prompt, neg_prompt, img_filename, mask_filename, seed, rembg, target_w, target_h)
                    else:
                        workflow = self._build_workflow(prompt, neg_prompt, img_filename, mask_filename, ckpt, steps, cfg, unet, clip, vae, rembg, denoise, profile, seed, upscaler)
                    
                    req = urllib.request.Request(f"{self.api_url}/prompt", data=json.dumps({"prompt": workflow}).encode('utf-8'))
                    req.add_header('Content-Type', 'application/json')
                    with urllib.request.urlopen(req) as response:
                        prompt_res = json.loads(response.read())
                        prompt_id = prompt_res.get("prompt_id")
                        
                    print(f"[{self.backend}] Prompt queued (ID: {prompt_id}). Waiting for generation...")
                    
                    # 5. Poll history until complete
                    import time
                    for i in range(600): # Wait up to 10 minutes
                        time.sleep(1.0)
                        req_hist = urllib.request.Request(f"{self.api_url}/history/{prompt_id}")
                        try:
                            with urllib.request.urlopen(req_hist) as res_hist:
                                history = json.loads(res_hist.read())
                                if prompt_id in history:
                                    outputs = history[prompt_id].get("outputs", {})
                                    
                                    # Find the output node that contains images (handles custom workflows)
                                    out_node = None
                                    for node_id, out_data in outputs.items():
                                        if "images" in out_data and len(out_data["images"]) > 0:
                                            out_node = out_data
                                            break
                                            
                                    if out_node:
                                        out_filename = out_node["images"][0]["filename"]
                                        out_type = out_node["images"][0].get("type", "output")
                                        out_subfolder = out_node["images"][0].get("subfolder", "")
                                    else:
                                        # Fallback for nodes like ComfyUI-HQ-Image-Save that return empty UI lists
                                        for n_id, n_data in workflow.items():
                                            c_type = n_data.get("class_type")
                                            if c_type in ["SaveEXR", "SaveEXRFrames"]:
                                                prefix = n_data.get("inputs", {}).get("filename_prefix", "ComfyUI")
                                                out_filename = f"{prefix}_00001_.exr"
                                                out_type = "output"
                                                out_subfolder = ""
                                                out_node = True
                                                break
                                            elif c_type == "SaveImage":
                                                prefix = n_data.get("inputs", {}).get("filename_prefix", "ComfyUI")
                                                out_filename = f"{prefix}_00001_.png"
                                                out_type = "output"
                                                out_subfolder = ""
                                                out_node = True
                                                break
                                                
                                    if out_node:
                                        
                                        # 6. Fetch the final image
                                        view_url = f"{self.api_url}/view?filename={urllib.parse.quote(out_filename)}&type={out_type}&subfolder={urllib.parse.quote(out_subfolder)}"
                                        req_view = urllib.request.Request(view_url)
                                        with urllib.request.urlopen(req_view) as res_view:
                                            img_data = res_view.read()
                                            nparr = np.frombuffer(img_data, np.uint8)
                                            img_out = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
                                            if img_out is not None:
                                                is_hdr = img_out.dtype in [np.float32, np.float16, np.float64]
                                                if img_out.ndim == 3 and img_out.shape[-1] == 4:
                                                    rgba_out = cv2.cvtColor(img_out, cv2.COLOR_BGRA2RGBA)
                                                    if not is_hdr:
                                                        rgba_out = rgba_out.astype(np.float32) / 255.0
                                                        linear_out = np.concatenate([rgba_out[..., :3] ** 2.2, rgba_out[..., 3:4]], axis=-1)
                                                    else:
                                                        linear_out = rgba_out.astype(np.float32)
                                                else:
                                                    # Convert BGR to RGB, normalize, and convert sRGB back to Linear
                                                    rgb_out = cv2.cvtColor(img_out, cv2.COLOR_BGR2RGB)
                                                    if not is_hdr:
                                                        rgb_out = rgb_out.astype(np.float32) / 255.0
                                                        linear_out = rgb_out ** 2.2
                                                    else:
                                                        linear_out = rgb_out.astype(np.float32)
                                                
                                                # Ensure exact dimension match (ComfyUI rounds to nearest 8 pixels)
                                                req_h, req_w = hdri_array.shape[:2]
                                                if linear_out.shape[:2] != (req_h, req_w):
                                                    linear_out = cv2.resize(linear_out, (req_w, req_h), interpolation=cv2.INTER_LANCZOS4)
                                                    
                                                return linear_out, None
                                    
                                    # If we reached here, the job finished but SaveImage failed (e.g. out of memory or missing node)
                                    error_details = json.dumps(history[prompt_id])
                                    return hdri_array.copy(), f"ComfyUI generation failed. Node error or no images output.\nDetails: {error_details}"
                        except urllib.error.HTTPError:
                            pass # History not ready yet
                            
                    print(f"[{self.backend}] Timed out waiting for ComfyUI.")
                    
            # Fallback to simulation if something failed
            return self._simulate_inpainting(hdri_array, mask_array), None
            
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode('utf-8', errors='ignore')
            print(f"[{self.backend}] HTTP Error {e.code}: {err_msg}")
            return hdri_array.copy(), f"HTTP {e.code}: {err_msg}"
        except (urllib.error.URLError, ConnectionRefusedError) as e:
            print(f"[{self.backend}] Connection failed: {e}")
            return hdri_array.copy(), f"Connection Failed: Is the AI Server running at {self.api_url}?"
        except Exception as e:
            print(f"[{self.backend}] Unexpected Error: {e}")
            return hdri_array.copy(), str(e)
            
    def _simulate_inpainting(self, hdri_array, mask_array):
        # Simulate AI replacing the masked area with a smooth blur (like an empty sky)
        try:
            import cv2
            out = hdri_array.copy()
            mask_u8 = (mask_array * 255).astype(np.uint8)
            # Simple Navier-Stokes inpainting as a lightweight local proxy for AI
            out_u8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
            inpainted = cv2.inpaint(out_u8, mask_u8, 3, cv2.INPAINT_NS)
            inpainted_float = inpainted.astype(np.float32) / 255.0
            
            # Blend it back (only over the masked area)
            blend_mask = np.clip(mask_array, 0, 1)
            if blend_mask.ndim == 2:
                blend_mask = blend_mask[..., np.newaxis]
                
            out = out * (1.0 - blend_mask) + inpainted_float * blend_mask
            return out
        except ImportError:
            return hdri_array.copy()

    def _upload_image(self, image_bytes, filename):
        boundary = 'wL36Yn8afVp8Ag7AmP8qZ0SA4n1v9T'
        data = []
        data.append(f'--{boundary}'.encode('utf-8'))
        data.append(f'Content-Disposition: form-data; name="image"; filename="{filename}"'.encode('utf-8'))
        data.append(b'Content-Type: image/png')
        data.append(b'')
        data.append(image_bytes)
        data.append(f'--{boundary}--'.encode('utf-8'))
        data.append(b'')
        
        body = b'\r\n'.join(data)
        req = urllib.request.Request(f"{self.api_url}/upload/image", data=body)
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read())
                return result.get("name")
        except Exception as e:
            print(f"[{self.backend}] Failed to upload image: {e}")
            return None

    def validate_custom_workflow(self, workflow_json):
        req = urllib.request.Request(f"{self.api_url}/object_info")
        try:
            with urllib.request.urlopen(req, timeout=3.0) as response:
                obj_info = json.loads(response.read())
        except Exception as e:
            return False, [f"Failed to connect to ComfyUI at {self.api_url}"]
            
        missing_models = []
        
        # Check if it's a standard UI workflow instead of an API workflow
        if isinstance(workflow_json, dict) and "nodes" in workflow_json and "links" in workflow_json:
            raise ValueError("It looks like you uploaded a standard ComfyUI workflow instead of an API workflow.\n\nPlease enable 'Enable Dev mode Options' in your ComfyUI settings (gear icon), then click 'Save (API Format)' and use that file instead.")
            
        for node_id, node in workflow_json.items():
            if not isinstance(node, dict):
                raise ValueError("Invalid workflow format. Please ensure you are using 'Save (API Format)' in ComfyUI.")
            class_type = node.get("class_type")
            if class_type in obj_info:
                inputs = node.get("inputs", {})
                req_inputs = obj_info[class_type].get("input", {}).get("required", {})
                for input_name, input_def in req_inputs.items():
                    if isinstance(input_def, list) and len(input_def) > 0 and isinstance(input_def[0], list):
                        available_options = input_def[0]
                        chosen_val = inputs.get(input_name)
                        # ComfyUI lists options as strings
                        if isinstance(chosen_val, str) and chosen_val not in available_options and not chosen_val.startswith("__"):
                            missing_models.append((class_type, input_name, chosen_val))
                            
        if missing_models:
            errors = []
            for ct, name, val in missing_models:
                errors.append(f"- Missing '{val}' in node {ct} ({name}).\n  Please download it from Hugging Face or Civitai to the correct ComfyUI/models folder.")
            return False, errors
        return True, []

    def _build_custom_workflow(self, workflow_json, prompt, neg_prompt, img_filename, mask_filename, seed=0, rembg=False, target_w=1024, target_h=1024):
        import copy
        wf = copy.deepcopy(workflow_json)
        
        load_image_found = False
        load_mask_found = False
        clip_encode_count = 0
        save_image_node_id = None
        
        for node_id, node in wf.items():
            class_type = node.get("class_type")
            inputs = node.get("inputs", {})
            
            if class_type in ["SaveImage", "SaveEXR", "SaveEXRFrames"]:
                save_image_node_id = node_id
                # Force SaveImage to re-execute by randomizing its filename_prefix
                # Use a hex string instead of digits so ComfyUI doesn't strip it as a counter!
                import uuid
                rand_str = uuid.uuid4().hex[:8]
                if "filename_prefix" in inputs:
                    inputs["filename_prefix"] = f"{inputs['filename_prefix']}_{rand_str}"
                else:
                    inputs["filename_prefix"] = f"ComfyUI_{rand_str}"
                    
            if class_type in ["EmptyLatentImage", "EmptySD3LatentImage", "EmptyFluxLatentImage", "EmptyHunyuanLatentImage"]:
                if "width" in inputs and "height" in inputs:
                    inputs["width"] = int(target_w)
                    inputs["height"] = int(target_h)
            
            # Apply UI seed
            for key in ["seed", "noise_seed"]:
                if key in inputs:
                    inputs[key] = int(seed)
                    
            if class_type == "LoadImage" and not load_image_found:
                inputs["image"] = img_filename
                load_image_found = True
            elif class_type == "LoadImageMask" and not load_mask_found:
                inputs["image"] = mask_filename
                load_mask_found = True
            elif class_type == "CLIPTextEncode":
                # Inject prompt into the first text encode, negative into the second
                if clip_encode_count == 0:
                    inputs["text"] = prompt
                elif clip_encode_count == 1:
                    inputs["text"] = neg_prompt
                clip_encode_count += 1
                
        if rembg and save_image_node_id:
            new_id = "9999"
            while new_id in wf:
                new_id = str(int(new_id) + 1)
                
            save_node = wf[save_image_node_id]
            if "images" in save_node.get("inputs", {}):
                prev_link = save_node["inputs"]["images"]
                wf[new_id] = {
                    "inputs": {
                        "images": prev_link,
                        "transparency": True,
                        "model": "isnet-general-use",
                        "post_processing": True,
                        "only_mask": False,
                        "alpha_matting": True,
                        "alpha_matting_foreground_threshold": 240,
                        "alpha_matting_background_threshold": 10,
                        "alpha_matting_erode_size": 10,
                        "background_color": "none"
                    },
                    "class_type": "Image Rembg (Remove Background)"
                }
                save_node["inputs"]["images"] = [new_id, 0]
                if save_node.get("class_type") in ["SaveEXR", "SaveEXRFrames"]:
                    save_node["class_type"] = "SaveImage"
                    old_inputs = save_node["inputs"]
                    save_node["inputs"] = {
                        "images": old_inputs.get("images"),
                        "filename_prefix": old_inputs.get("filename_prefix", "ComfyUI")
                    }
                    
        return wf

    def _build_workflow(self, prompt, neg_prompt, img_filename, mask_filename, ckpt, steps_override, cfg_override, unet="", clip="", vae="", rembg=False, denoise=1.0, profile="Auto-Detect", seed=0, upscaler="None"):
        import uuid
        # Auto-detect turbo/flux models for optimal settings
        unet_lower = (unet or "").lower()
        ckpt_lower = (ckpt or "").lower()
        
        is_turbo = "turbo" in ckpt_lower or "turbo" in unet_lower
        is_zturbo = "zturbo" in ckpt_lower or "zturbo" in unet_lower or "z-image-turbo" in ckpt_lower or "z-image-turbo" in unet_lower
        is_distilled = "schnell" in ckpt_lower or "schnell" in unet_lower or "klein" in ckpt_lower or "klein" in unet_lower
        is_flux = "flux" in ckpt_lower or "flux" in unet_lower
        is_ltx = "ltx" in ckpt_lower or "ltx" in unet_lower
        
        # Override with explicit profile if selected
        if profile != "Auto-Detect":
            is_turbo = profile == "SDXL Turbo"
            is_zturbo = profile == "Z-Image Turbo"
            is_distilled = profile == "Flux Schnell/Klein"
            is_flux = profile == "Flux Dev"
            is_ltx = profile == "LTX-2"
        
        if is_zturbo:
            steps = min(steps_override, 8) if steps_override > 8 else (8 if steps_override >= 20 else steps_override)
            cfg = 1.5 if cfg_override >= 7.0 else cfg_override
            sampler = "euler"
            scheduler = "simple"
        elif is_distilled:
            steps = min(steps_override, 8) if steps_override > 8 else (4 if steps_override >= 20 else steps_override)
            cfg = 1.5 if cfg_override >= 7.0 else cfg_override
            sampler = "euler"
            scheduler = "simple"
        elif is_turbo:
            steps = 4 if steps_override >= 20 else steps_override
            cfg = 1.5 if cfg_override >= 7.0 else cfg_override
            sampler = "dpmpp_sde_gpu"
            scheduler = "karras"
        elif is_flux:
            steps = steps_override
            cfg = 3.5 if cfg_override >= 7.0 else cfg_override
            sampler = "euler"
            scheduler = "simple"
        elif is_ltx:
            steps = steps_override
            cfg = 3.0 if cfg_override >= 7.0 else cfg_override
            sampler = "euler"
            scheduler = "normal"
        else:
            steps = steps_override
            cfg = cfg_override
            sampler = "euler"
            scheduler = "normal"
        
        workflow = {
            "3": {
                "inputs": {"seed": int(seed), "steps": steps, "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler, "denoise": float(denoise), "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["13", 0]},
                "class_type": "KSampler"
            },
            "6": {
                "inputs": {"text": prompt, "clip": ["4", 1]},
                "class_type": "CLIPTextEncode"
            },
            "7": {
                "inputs": {"text": neg_prompt, "clip": ["4", 1]},
                "class_type": "CLIPTextEncode"
            },
            "8": {
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
                "class_type": "VAEDecode"
            },
            "9": {
                "inputs": {
                    "filename_prefix": f"hdri_inpaint_{uuid.uuid4().hex[:8]}",
                    "images": ["8", 0],
                    "tonemap": "sRGB",
                    "version": 1,
                    "start_frame": 1001,
                    "frame_pad": 4,
                    "save_workflow": "none",
                    "create_path_if_missing": False
                },
                "class_type": "SaveEXR"
            },
            "10": {
                "inputs": {"pixels": ["11", 0], "vae": ["4", 2]},
                "class_type": "VAEEncode"
            },
            "13": {
                "inputs": {"samples": ["10", 0], "mask": ["12", 0]},
                "class_type": "SetLatentNoiseMask"
            },
            "11": {
                "inputs": {"image": img_filename, "upload": "image"},
                "class_type": "LoadImage"
            },
            "12": {
                "inputs": {"image": mask_filename, "channel": "red", "upload": "image"},
                "class_type": "LoadImageMask"
            }
        }
        
        if unet:
            workflow["4"] = {
                "inputs": {"unet_name": unet, "weight_dtype": "default"},
                "class_type": "UNETLoader"
            }
        else:
            workflow["4"] = {
                "inputs": {"ckpt_name": ckpt},
                "class_type": "CheckpointLoaderSimple"
            }

        if is_zturbo:
            workflow["17"] = {
                "inputs": {"shift": 3.0, "model": ["4", 0]},
                "class_type": "ModelSamplingAuraFlow"
            }
            workflow["3"]["inputs"]["model"] = ["17", 0]
            
            workflow["18"] = {
                "inputs": {"conditioning": ["6", 0]},
                "class_type": "ConditioningZeroOut"
            }
            workflow["3"]["inputs"]["negative"] = ["18", 0]
            if "7" in workflow:
                del workflow["7"]

        if clip:
            clip_type = "lumina2" if is_zturbo else "flux2"
            workflow["14"] = {
                "inputs": {"clip_name": clip, "type": clip_type, "device": "default"},
                "class_type": "CLIPLoader"
            }
            workflow["6"]["inputs"]["clip"] = ["14", 0]
            if "7" in workflow:
                workflow["7"]["inputs"]["clip"] = ["14", 0]

        if vae:
            workflow["15"] = {
                "inputs": {"vae_name": vae},
                "class_type": "VAELoader"
            }
            workflow["8"]["inputs"]["vae"] = ["15", 0]
            workflow["10"]["inputs"]["vae"] = ["15", 0]

        if rembg:
            workflow["16"] = {
                "inputs": {
                    "images": ["8", 0],
                    "transparency": True,
                    "model": "isnet-general-use",
                    "post_processing": True,
                    "only_mask": False,
                    "alpha_matting": True,
                    "alpha_matting_foreground_threshold": 240,
                    "alpha_matting_background_threshold": 10,
                    "alpha_matting_erode_size": 10,
                    "background_color": "none"
                },
                "class_type": "Image Rembg (Remove Background)"
            }
            workflow["9"]["class_type"] = "SaveImage"
            workflow["9"]["inputs"] = {
                "filename_prefix": f"hdri_inpaint_{uuid.uuid4().hex[:8]}",
                "images": ["16", 0]
            }

        if upscaler and upscaler.lower() != "none" and upscaler.strip() != "":
            workflow["20"] = {
                "inputs": {"model_name": upscaler},
                "class_type": "UpscaleModelLoader"
            }
            img_src = ["16", 0] if rembg else ["8", 0]
            workflow["21"] = {
                "inputs": {"upscale_model": ["20", 0], "image": img_src},
                "class_type": "ImageUpscaleWithModel"
            }
            workflow["9"]["inputs"]["images"] = ["21", 0]
            
        return workflow
