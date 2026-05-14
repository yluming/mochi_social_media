# -*- coding: utf-8 -*-
"""
Mochi Scene Direct Generator (mochi-scene-direct)
Workflow: 
  Iterate through JSON panels -> Generate 3 independent 3:4 images.
  Optimized for Mochi size and typography layout.
"""

import argparse
import base64
import json
import os
import sys
import time
import re
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
REF_LAYOUT     = "storyboard_ref.png"  # For typography / cinematic feel

# ─────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────

def read_api_key(path: str) -> str:
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
                raise RuntimeError(f"API returned empty or invalid data list")

            b64_data = data_list[0].get("b64_json")
            if not b64_data:
                raise RuntimeError(f"No b64_json in data[0].")
            return base64.b64decode(b64_data)
        except Exception as e:
            last_err = e
            print(f"   [warn] attempt {attempt} error: {e}")
    raise RuntimeError(f"Failed after {max_retries} attempts: {last_err}")

# ─────────────────────────────────────────────────────────────
# Prompt Builder
# ─────────────────────────────────────────────────────────────

def build_scene_prompt(panel_data: dict, story_theme: str, scene_context: str) -> str:
    idx = panel_data.get("index", "?")
    txt = panel_data.get("text", "").replace("\n", " ")
    pos = panel_data.get("mochi_pos", "center")
    
    # Analyze scene context to find the specific description for this panel
    # The storyboard_description often looks like "1. Desc... 2. Desc... 3. Desc..."
    panel_desc = ""
    match = re.search(f"{idx}\\.\\s*(.*?)(?=\\d\\.\\s*|$)", scene_context, re.DOTALL)
    if match:
        panel_desc = match.group(1).strip()
    else:
        panel_desc = scene_context # Fallback to the whole thing if regex fails
    
    return (
        "You are a visionary cinematic photographer and digital artist. "
        "Generate a single standalone 3:4 vertical healing-style illustration. "
        
        # Atmosphere & Technicals
        "VISUAL STYLE: Cinematic film-stock grain, muted premium colors, high-end materiality. "
        "IMPORTANT LIGHTING: Use the specific environmental lighting described in the PANEL ACTION below (e.g., dim office, harsh corridor, or warm desk lamp). "
        "Do NOT strictly follow the lighting of Reference 2 if it conflicts with the scene's required atmosphere; Reference 2 is for film texture and quality only. "
        
        f"SCENE THEME: {story_theme}. "
        f"PANEL ACTION: {panel_desc}. "
        
        # Mochi Placement & Sizing
        f"CHARACTER POSITION: Place the white round creature (Mochi) at the {pos}. "
        "CHARACTER PERSONALITY: Mochi is a peaceful, curious, and gentle observer. "
        "CRITICAL: Avoid making Mochi look sad, distressed, or heavy. His gaze should be 'clear and curious' (清澈而好奇). "
        "Mochi should be a medium-subject in the frame, clearly visible and well-integrated. "
        
        # References
        "Reference 1 (Mochi character): Reproduce this exact character. "
        "Reference 2 (Visual style): Match the film-stock texture and aesthetic quality. "
        
        # Typography
        f"CHINESE TEXT OVERLAY: '{txt}'. "
        "TYPOGRAPHY INSTRUCTION: Use a beautiful, casual ARTISTIC HANDWRITTEN font. "
        "Place the text in a cinematic subtitle position (usually bottom center) or balanced against the character's position. "
        "The text color should be a soft, light-extracted neutral (like ivory or warm highlight white). "
        "NO quotes, NO brackets. The text must feel like a natural part of the cinematic scene."
    )

# ─────────────────────────────────────────────────────────────
# Execution
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mochi Scene Direct Generator.")
    parser.add_argument("--content_file", required=True)
    parser.add_argument("--api_key_path", default=None)
    parser.add_argument("--scene_index", type=str, default=None, help="Comma-separated indices of scenes to generate (e.g., '1,2')")
    args = parser.parse_args()

    target_scenes = None
    if args.scene_index:
        target_scenes = [int(x.strip()) for x in args.scene_index.split(",")]

    # ── API Key ──
    candidates = [
        Path(args.api_key_path) if args.api_key_path else None,
        SKILL_DIR.parent.parent / "api_key_abroad.txt",
        SKILL_DIR.parent.parent / ".env",
        SKILL_DIR / ".env",
    ]
    key_file = next((p for p in candidates if p and p.exists()), None)
    if not key_file: raise FileNotFoundError(f"No API key file found. Checked: {[str(p) for p in candidates if p]}")
    api_key = read_api_key(str(key_file))

    # ── Load data ──
    with open(args.content_file, encoding="utf-8") as f:
        episode = json.load(f)
        if isinstance(episode, list): episode = episode[0]
        
    ep_date = episode.get("date", date.today().strftime("%Y-%m-%d"))
    out_dir = SKILL_DIR / "output" / ep_date
    out_dir.mkdir(parents=True, exist_ok=True)

    story_theme = episode.get("story_theme", "")
    scene_context = episode.get("storyboard_description", "")
    panels = episode.get("panels", [])

    print(f"\n[*] Starting Direct Generation for Episode: {episode.get('id', '???')}")
    print(f"[*] Output directory: {out_dir}\n")

    for i, p_data in enumerate(panels, start=1):
        if target_scenes and i not in target_scenes:
            continue
            
        scene_path = out_dir / f"scene_{i}.jpg"
        target_scene_path = get_unique_path(scene_path)
        
        print(f"[{i}/3] Generating Independent Scene {i}...")
        prompt = build_scene_prompt(p_data, story_theme, scene_context)
        
        refs = [
            str(REFS_DIR / REF_MOCHI),
            str(REFS_DIR / REF_STYLE)
        ]
        
        img_bytes = call_image_api(api_key, prompt, ref_paths=refs)
        target_scene_path.write_bytes(img_bytes)
        print(f"   OK: {target_scene_path.name} ({len(img_bytes)//1024} KB)")
        
        if i < 3:
            print("   [cooldown] Waiting 15s before next request...\n")
            time.sleep(15)

    # ── Write Caption ──
    caption_path = out_dir / "caption.txt"
    caption_path.write_text(episode.get("caption", ""), encoding="utf-8")

    print(f"\n[DONE] All {len(panels)} scenes generated. Files in: {out_dir}")

if __name__ == "__main__":
    main()
