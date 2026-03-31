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


def get_unique_path(path: Path) -> Path:
    """If file exists, append _1, _2... etc."""
    if not path.exists():
        return path
    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while (parent / f"{stem}_{counter}{suffix}").exists():
        counter += 1
    return parent / f"{stem}_{counter}{suffix}"


def call_image_api(api_key: str, prompt: str, ref_paths: list = None,
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
                print(f"   [debug] Full Response: {resp.text}")
                raise RuntimeError(f"API returned empty or invalid data list: {resp.text}")

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
    story_theme = episode.get("story_theme", "")
    layout_desc = episode.get("storyboard_description", "")
    panels      = episode.get("panels", [])
    
    panels_info = ""
    for p in panels:
        idx = p.get("index", "?")
        txt = p.get("text", "").replace("\n", " ")
        panels_info += f"Panel {idx} Chinese text: {txt}. "

    # Typography Extraction & Unified Cohesion
    return (
        "You are a visionary cinematic graphic designer and colorist. "
        "Generate a single 3:4 vertical image consisting of 3 horizontal cinematic panels. "
        "IMPORTANT: Seamless borderless layout. NO black bars, no frames. "
        
        # Color Grading & Atmosphere
        "VISUAL STYLE: Unified cinematic color grading. Use soft, natural light transitions. "
        "Maintain a lower-saturation, high-end film-stock aesthetic. "
        "Atmosphere should be quiet, clean, and highly sophisticated. "
        
        f"Overall story theme: {story_theme}. "
        f"Detailed panel descriptions: {layout_desc}. "
        
        # References
        "Reference 1 (Mochi character): Reproduce this exact character. "
        "Reference 2 (Visual style): Match the film-stock texture and atmosphere. "
        "Reference 3 (Layout Style): Match the typography placement and artistic feel. "
        
        # Typography Style, Extraction & Unified Cohesion
        "CRITICAL TYPOGRAPHY INSTRUCTION: Use a CASUAL, ARTISTIC HANDWRITTEN STYLE font for all text, mimicking the brush strokes in Reference 3. "
        "Establish a UNIFIED PRIMARY COLOR for all text. Extract this color organically from the scene's dominant cinematic highlights (e.g., a warm pearl, soft champagne, or muted neutral from the environmental light). "
        "Panel 1: MAIN TITLE. This should be larger, bold, and more prominent, reflecting the core theme. "
        "Panels 2 & 3: NARRATIVE CAPTIONS. These use the same font and color but must be smaller and more understated, like gentle cinematic subtitles. "
        "NO BRACKETS, NO QUOTES around the Chinese text. "
        f"{panels_info}"
        
        "The final result must combine high-end artistic handwriting with light-distilled colors for a cohesive, soulful aesthetic."
    )


def build_expansion_prompt(strip_index: int, panel_data: dict, story_theme: str) -> str:
    # Use the context to help the AI understand WHAT it is expanding.
    context = panel_data.get("text", "").replace("\n", " ")
    return (
        "You are a high-fidelity image restoration and expansion artist. "
        f"Context of the scene: {context} (Theme: {story_theme}). "
        "Reference 1 (Source Strip): This is your ONLY DEFINITIVE source for content, character, and style. "
        
        # Expansion task
        "Generate a full 3:4 vertical cinematic illustration by expanding Reference 1. "
        "IMPORTANT: You MUST maintain 100% visual consistency with the subjects (Mochi), lighting, and colors in the center strip. "
        "Extend the background (top and bottom) seamlessly while keeping the center identical. "
        
        # Removal task
        "CRITICAL: CLEANLY REMOVE all text overlays. The final image must be a PURE cinematic scene. "
        "No text, no watermarks, no split screens. Just one continuous, high-quality cinematic environment."
    )


# ─────────────────────────────────────────────────────────────
# Main execution steps
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mochi Story Series - Storyboard First Workflow.")
    parser.add_argument("--content_file", required=True)
    parser.add_argument("--date", default=None)
    parser.add_argument("--api_key_path", default=None)
    parser.add_argument("--force_all", action="store_true", help="Ignore existing scene files")
    parser.add_argument("--scene_index", type=int, default=0, help="Only generate/retry a specific scene (1, 2, or 3)")
    parser.add_argument("--storyboard_only", action="store_true", help="Stop after generating the master storyboard")
    parser.add_argument("--new_storyboard", action="store_true", help="Force regenerate the master storyboard")
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
    if args.date:
        ep_date = args.date
    out_dir = SKILL_DIR / "output" / ep_date
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Generate Master Storyboard ──
    sb_path = out_dir / "storyboard.jpg"
    
    target_sb_path = sb_path
    if sb_path.exists() and not args.new_storyboard:
        print("[*] Found existing storyboard.jpg, using it.")
    else:
        if sb_path.exists():
             target_sb_path = get_unique_path(sb_path)

        print(f"[1/2] Generating Master Storyboard ({target_sb_path.name})...")
        prompt = build_master_storyboard_prompt(episode)
        refs = [str(REFS_DIR / REF_MOCHI), str(REFS_DIR / REF_STYLE), str(REFS_DIR / REF_STORYBOARD)]
        img_bytes = call_image_api(api_key, prompt, ref_paths=refs)
        target_sb_path.write_bytes(img_bytes)
        print(f"   OK: {target_sb_path.name} ({len(img_bytes)//1024} KB)")
        sb_path = target_sb_path # Use this version for subsequent steps
    
    if args.storyboard_only:
        print("\n[!] --storyboard_only set. Exiting.")
        sys.exit(0)

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
        target_scene_path = get_unique_path(scene_path)
        
        print(f"[2/2] Expanding strip {idx} for {target_scene_path.name} (No text)...")
        prompt = build_expansion_prompt(idx, p_data, story_theme)
        # ONLY use the strip as reference to avoid model confusion and visual drift!
        refs = [str(s_path)] 
        # Fallback context if needed
        if idx == 3:
            refs = [str(s_path), str(REFS_DIR / REF_MOCHI), str(REFS_DIR / REF_STYLE)]
            
        img_bytes = call_image_api(api_key, prompt, ref_paths=refs)
        target_scene_path.write_bytes(img_bytes)
        print(f"   OK: {target_scene_path.name} ({len(img_bytes)//1024} KB)")
        
        if idx < 3:
            print("   [cooldown] Waiting 15s before next request...\n")
            time.sleep(15)

    # ── Write Caption ──
    caption_path = out_dir / "caption.txt"
    caption_path.write_text(episode.get("caption", ""), encoding="utf-8")

    print(f"\n✅ All tasks completed. Files in: {out_dir}")

if __name__ == "__main__":
    main()
