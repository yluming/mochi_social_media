# -*- coding: utf-8 -*-
"""
Mochi Story Series Generator (mochi-story-series) - INVERSE WORKFLOW
Version: Storyboard-First

Workflow:
  1. Generate one 3:4 Masters Storyboard (3 panels + text).
  2. Crop Storyboard into 3 cinematic strips (9:4).
  3. Use AI to expand each strip back to 3:4 while REMOVING text.
"""

import argparse
import base64
import json
import os
import sys
import time
from datetime import date
from io import BytesIO
from pathlib import Path

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
API_BASE_IMAGE = "https://imodel-ap1.iflyoversea.com"
IMAGE_MODEL    = "gemini-3.1-flash-image-preview"

SKILL_DIR = Path(__file__).parent.parent
REFS_DIR  = SKILL_DIR / "references"

# Reference images
REF_MOCHI      = "mochi_ref.png"       # Standalone Mochi character
REF_STYLE      = "style_ref.png"       # Visual style guide
REF_STORYBOARD = "storyboard_ref.png"  # Layout reference for the multi-panel board


# ─────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────

def read_api_key(path: str) -> str:
    import re
    with open(path, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"^API_KEY_ABROAD\s*=\s*(.+)$", content, re.MULTILINE)
    if m:
        return m.group(1).strip().strip("'\"")
    m = re.search(r"['\"](.+?)['\"]", content)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot parse API key from: {path}")


def img_to_data_uri(path: str, max_size_mb: float = 0.5) -> tuple[str, str]:
    from PIL import Image
    suffix = Path(path).suffix.lower()
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    max_bytes = int(max_size_mb * 1024 * 1024)
    quality = 92
    for _ in range(6):
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= max_bytes:
            break
        quality = max(int(quality * (max_bytes / buf.tell()) * 0.9), 40)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}", "image/jpeg"


def call_image_api(api_key: str, prompt: str, ref_paths: list[str] = None,
                   max_retries: int = 5, retry_delay: float = 15.0) -> bytes:
    hdrs = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    ext = {"prompt": prompt, "size": "3:4"}
    if ref_paths:
        encoded_refs = []
        for rp in ref_paths:
            if os.path.exists(rp):
                data_uri, _ = img_to_data_uri(rp)
                encoded_refs.append(data_uri)
                print(f"   [ref] {Path(rp).name}  ({len(data_uri) // 1024} KB encoded)")
        if encoded_refs:
            ext["image"] = encoded_refs
            ext["imageType"] = "image/jpeg"

    payload = {
        "model":     IMAGE_MODEL,
        "platform":  "google",
        "stream":    False,
        "extParams": ext,
    }

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                print(f"   [retry {attempt}/{max_retries}] waiting {retry_delay}s...")
                time.sleep(retry_delay)
            
            resp = requests.post(f"{API_BASE_IMAGE}/api/v1/images/generate", 
                                 headers=hdrs, json=payload, timeout=180, verify=False)
            resp.raise_for_status()
            
            result = resp.json()
            code = result.get("code")
            if code and str(code) != "0":
                raise RuntimeError(f"API error code={code}: {result.get('message', '')}")
            
            data_list = result.get("data")
            if not data_list or not isinstance(data_list, list) or len(data_list) == 0:
                raise RuntimeError(f"API returned empty or invalid data list: {result.get('message', 'No message')}")

            b64_data = data_list[0].get("b64_json")
            if not b64_data:
                raise RuntimeError(f"No b64_json in data[0].")
            return base64.b64decode(b64_data)
        except Exception as e:
            last_err = e
            print(f"   [warn] attempt {attempt} error: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"   [debug] response text: {e.response.text[:500]}")
    raise RuntimeError(f"Failed after {max_retries} attempts: {last_err}")


# ─────────────────────────────────────────────────────────────
# Step-specific prompt builders
# ─────────────────────────────────────────────────────────────

def build_master_storyboard_prompt(episode: dict) -> str:
    title_text = episode.get("cover_title", "")
    story_theme = episode.get("story_theme", "")
    layout_desc = episode.get("storyboard_description", "")
    
    panels_info = ""
    for p in episode.get("panels", []):
        idx = p.get("index", "?")
        txt = p.get("text", "").replace("\n", " ")
        panels_info += f"Panel {idx} Chinese text overlay: 「{txt}」. "

    return (
        "You are a professional cinematic storyboard artist. "
        f"Generate a single 3:4 storyboard image with 3 horizontal panels. "
        f"Overall story theme: {story_theme}. "
        f"Detailed panel descriptions: {layout_desc}. "
        
        # References instruction
        "Reference 1 (Mochi character): Reproduce this exact character in all panels. "
        "Reference 2 (Visual style): Match this cinematic 3D CG lighting and rendering quality. "
        "Reference 3 (Layout): Match this 3-panel vertical stack layout with thin black separators. "
        
        # Text instructions
        f"Overlay the following Chinese text on the panels as shown in Reference 3. "
        "Use a casual, handwritten-style font, similar to the reference. "
        f"Panel 1 Title: 「{title_text}」. "
        f"{panels_info}"
        
        "Ensure the text is legible and artistically integrated into the scenes."
    )


def build_expansion_prompt(strip_index: int, panel_data: dict, story_theme: str) -> str:
    original_text = panel_data.get("text", "").replace("\n", " ")
    mochi_pos = panel_data.get("mochi_pos", "center")
    
    return (
        "You are a cinematic concept artist. "
        "Reference 1 (Cinematic Source): This is a horizontal movie-style fragment of a scene. "
        "Reference 2 (Character): Maintain this exact character appearance. "
        "Reference 3 (Style): Match this cinematic CG rendering quality. "
        
        # Generation task
        "Generate a SINGLE-PANEL full 3:4 vertical cinematic illustration. "
        "IMPORTANT: This is NOT a storyboard. DO NOT create multiple panels, borders, or split-screens. "
        "Use the horizontal composition from Reference 1 as your core content. "
        "Extend the background upward and downward naturally to fill the entire 3:4 frame. "
        "The final image must be a continuous, single-perspective cinematic environment with NO text."
    )


# ─────────────────────────────────────────────────────────────
# Main execution steps
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mochi Story Series - Storyboard First Workflow.")
    parser.add_argument("--content_file", required=True)
    parser.add_argument("--date", default=None)
    parser.add_argument("--api_key_path", default=None)
    parser.add_argument("--force_all", action="store_true", help="Ignore existing files")
    parser.add_argument("--scene_index", type=int, default=0, help="Only generate/retry a specific scene (1, 2, or 3)")
    args = parser.parse_args()

    # ── API Key ──
    candidates = [
        Path(args.api_key_path) if args.api_key_path else None,
        SKILL_DIR.parent.parent.parent / ".env",
        SKILL_DIR.parent.parent / ".env",
        SKILL_DIR / ".env",
    ]
    key_file = next((p for p in candidates if p and p.exists()), None)
    if not key_file: raise FileNotFoundError("No API key file found.")
    api_key = read_api_key(str(key_file))

    # ── Load data ──
    with open(args.content_file, encoding="utf-8") as f:
        episode = json.load(f)[0] # simplified for demo
    ep_date = episode.get("date", date.today().strftime("%Y-%m-%d"))
    out_dir = SKILL_DIR / "output" / ep_date
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Generate Master Storyboard ──
    sb_path = out_dir / "storyboard.jpg"
    if not sb_path.exists() or args.force_all:
        print("[1/2] Generating Master Storyboard (storyboard.jpg)...")
        prompt = build_master_storyboard_prompt(episode)
        refs = [str(REFS_DIR / REF_MOCHI), str(REFS_DIR / REF_STYLE), str(REFS_DIR / REF_STORYBOARD)]
        img_bytes = call_image_api(api_key, prompt, ref_paths=refs)
        sb_path.write_bytes(img_bytes)
        print(f"   OK: storyboard.jpg ({len(img_bytes)//1024} KB)")
        print("   [cooldown] Waiting 15s before next phase...\n")
        time.sleep(15)
    else:
        print("[*] Found existing storyboard.jpg, skipping Step 1.")

    # ── Step 2: Physical Cropping into Strips ──
    from PIL import Image
    sb_img = Image.open(sb_path).convert("RGB")
    W, H = sb_img.size
    
    panel_h_approx = H // 3
    strips = []
    for idx in range(3):
        top = idx * panel_h_approx
        bottom = (idx + 1) * panel_h_approx
        strip = sb_img.crop((0, top, W, bottom))
        
        strip_path = out_dir / f"tmp_strip_{idx+1}.jpg"
        strip.save(strip_path, quality=95)
        strips.append(strip_path)
    print(f"[*] Cropped 3 strips into {out_dir}/tmp_strip_*.jpg")

    # ── Step 3: Expand Strips into Full Scenes (Clean, No Text) ──
    story_theme = episode.get("story_theme", "")
    panels = episode.get("panels", [])
    
    for idx, (s_path, p_data) in enumerate(zip(strips, panels), start=1):
        if args.scene_index != 0 and args.scene_index != idx:
            continue

        scene_path = out_dir / f"scene_{idx}.jpg"
        if scene_path.exists() and not args.force_all and args.scene_index == 0:
            print(f"[*] Found existing scene_{idx}.jpg, skipping.")
            continue
            
        print(f"[2/2] Expanding strip {idx} for scene_{idx}.jpg (No text)...")
        prompt = build_expansion_prompt(idx, p_data, story_theme)
        # Ref 1: The cropped strip. Ref 2: Mochi char. Ref 3: Style
        refs = [str(s_path), str(REFS_DIR / REF_MOCHI), str(REFS_DIR / REF_STYLE)]
        img_bytes = call_image_api(api_key, prompt, ref_paths=refs)
        scene_path.write_bytes(img_bytes)
        print(f"   OK: scene_{idx}.jpg ({len(img_bytes)//1024} KB)")
        
        if idx < 3:
            print("   [cooldown] Waiting 15s before next request...\n")
            time.sleep(15)

    # ── Write Caption ──
    caption_path = out_dir / "caption.txt"
    caption_path.write_text(episode.get("caption", ""), encoding="utf-8")

    print(f"\n✅ All tasks completed. Files in: {out_dir}")

if __name__ == "__main__":
    main()
