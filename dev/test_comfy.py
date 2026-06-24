import urllib.request
import json
import numpy as np

api_url = "http://127.0.0.1:8188"
workflow = {
    "3": {
        "inputs": {"seed": int(np.random.randint(0, 1000000)), "steps": 20, "cfg": 8, "sampler_name": "euler", "scheduler": "normal", "denoise": 1, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["10", 0]},
        "class_type": "KSampler"
    },
    "4": {
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
        "class_type": "CheckpointLoaderSimple"
    },
    "6": {
        "inputs": {"text": "hello", "clip": ["4", 1]},
        "class_type": "CLIPTextEncode"
    },
    "7": {
        "inputs": {"text": "bad", "clip": ["4", 1]},
        "class_type": "CLIPTextEncode"
    },
    "8": {
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        "class_type": "VAEDecode"
    },
    "9": {
        "inputs": {"filename_prefix": "hdri_inpaint", "images": ["8", 0]},
        "class_type": "SaveImage"
    },
    "10": {
        "inputs": {"grow_mask_by": 6, "pixels": ["11", 0], "vae": ["4", 2], "mask": ["12", 0]},
        "class_type": "VAEEncodeForInpaint"
    },
    "11": {
        "inputs": {"image": "hdri_inpaint_target.png", "upload": "image"},
        "class_type": "LoadImage"
    },
    "12": {
        "inputs": {"image": "hdri_inpaint_mask.png", "channel": "red", "upload": "image"},
        "class_type": "LoadImageMask"
    }
}

req = urllib.request.Request(f"{api_url}/prompt", data=json.dumps({"prompt": workflow}).encode('utf-8'))
req.add_header('Content-Type', 'application/json')
try:
    with urllib.request.urlopen(req) as response:
        print("Prompt queued successfully!", response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.read().decode('utf-8')}")
except Exception as e:
    print(f"Exception: {e}")
