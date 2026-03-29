# -*- coding: utf-8 -*-
"""
Mochi 情绪消解封面生成器 (Cover Dissolver)

Usage:
  python generate_cover.py [--date YYYY-MM-DD] [--top_ref <path>] [--bottom_ref <path>]

Flow:
  1. Read today's entry from topics_library.md "Mochi翻译：情绪消解指南" section
  2. Generate top character image via doubao-seedream-5-lite (with reference)
  3. Generate bottom character image via doubao-seedream-5-lite (with reference)
  4. Composite final cover via gemini-3.1-flash-image-preview (reference + text overlay)
"""

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from io import BytesIO

import requests

# Fix Windows GBK encoding for emoji/CJK output
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", buffering=1)

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

# doubao for character image generation (domestic endpoint)
API_BASE_DOUBAO = "https://imodel.xfinfr.com"
DOUBAO_MODEL    = "doubao-seedream-5-lite"

# gemini for final composite (abroad endpoint)
API_BASE_GEMINI = "https://imodel-ap1.iflyoversea.com"
GEMINI_MODEL    = "gemini-3.1-flash-image-preview"

SKILL_DIR = Path(__file__).parent.parent
REFS_DIR  = SKILL_DIR / "references"

DEFAULT_API_KEY_PATH        = "D:/Test/Mochi_test/api_key.env.txt"
DEFAULT_API_KEY_ABROAD_PATH = "D:/Test/Mochi_test/api_key_abroad.txt"
DEFAULT_MD_FILE             = "D:/Test/Mochi_test/topics_library.md"
DEFAULT_OUTPUT_BASE         = "D:/Test/Mochi_test/output"

REF_TOP    = "top_ref.png"      # reference for top character (purple-hair girl)
REF_BOTTOM = "bottom_ref.png"   # reference for bottom character (white fluffy ball)
REF_LAYOUT = "cover_layout_ref.png"  # reference for final cover layout (two-panel comic)


# ─────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────

def read_api_key(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        m = re.search(r"['\"](.+?)['\"]", f.read())
    if not m:
        raise ValueError(f"Cannot parse API key from: {path}")
    return m.group(1)


def normalize_date(d: str) -> str:
    parts = re.split(r"[-/]", d.strip())
    if len(parts) == 3:
        try:
            y, m, day = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{y:04d}-{m:02d}-{day:02d}"
        except ValueError:
            pass
    return d.strip()


def resize_image_bytes(img_bytes: bytes, max_px: int = 512) -> bytes:
    """Resize image so longest side <= max_px, return JPEG bytes."""
    from PIL import Image
    img = Image.open(BytesIO(img_bytes))
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_px, max_px), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def img_file_to_base64(path: str, max_px: int = 512) -> str:
    """Read image file, resize, return base64 string."""
    raw = Path(path).read_bytes()
    resized = resize_image_bytes(raw, max_px)
    return base64.b64encode(resized).decode()


# ─────────────────────────────────────────────────────────────
# Parse topics_library.md — "Mochi翻译" section
# ─────────────────────────────────────────────────────────────

def parse_dissolver_section(md_file: str, target_date: str) -> dict:
    """
    Parse the '## 2. Mochi 翻译：情绪消解指南' table.
    Returns: {date, group, scene, cover_text, dissolver_text}
    """
    with open(md_file, encoding="utf-8") as f:
        content = f.read()

    section_match = re.search(r"## 2\..+?(?=\n## \d+\.|\Z)", content, re.DOTALL)
    if not section_match:
        raise ValueError("Cannot find '## 2. Mochi 翻译' section in topics_library.md")
    section_text = section_match.group(0)

    table_lines = [l.strip() for l in section_text.splitlines() if l.strip().startswith("|")]
    if len(table_lines) < 3:
        raise ValueError("No valid markdown table found in 'Mochi翻译' section")

    headers = [h.strip() for h in table_lines[0].split("|") if h.strip()]

    def find_col(*keywords):
        for kw in keywords:
            for i, h in enumerate(headers):
                if kw in h:
                    return i
        return None

    date_col      = find_col("更新日期")
    group_col     = find_col("人群")
    scene_col     = find_col("场景", "黑话")
    cover_col     = find_col("封面", "文案")
    dissolver_col = find_col("正文", "黑色幽默")

    if date_col is None:
        raise ValueError("Cannot find '更新日期' column")

    norm_target = normalize_date(target_date)
    results = []

    for row_line in table_lines[2:]:
        cells = [c.strip() for c in row_line.split("|") if c.strip()]
        if len(cells) <= date_col:
            continue
        if normalize_date(cells[date_col]) == norm_target:
            def get(col):
                return cells[col].strip() if col is not None and len(cells) > col else ""

            results.append({
                "date":           cells[date_col],
                "group":          get(group_col),
                "scene":          get(scene_col),
                "cover_text":     get(cover_col),
                "dissolver_text": get(dissolver_col),
            })

    if not results:
        raise ValueError(f"Date {target_date} (normalized: {norm_target}) not found in 'Mochi翻译' section")

    return results


# ─────────────────────────────────────────────────────────────
# Image generation: doubao-seedream-5-lite (character images)
# ─────────────────────────────────────────────────────────────

def generate_doubao_image(api_key: str, prompt: str, ref_image_path: str = None,
                          width: int = 1024, height: int = 1024) -> bytes:
    """
    Generate an image via doubao-seedream-5-lite.
    Optionally pass a reference image for style/character consistency.
    Returns raw image bytes.
    """
    url = f"{API_BASE_DOUBAO}/api/v1/images/generate"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    ext_params = {
        "prompt": prompt,
        "width": width,
        "height": height,
    }

    # Attach reference image if provided
    if ref_image_path and Path(ref_image_path).exists():
        b64 = img_file_to_base64(ref_image_path, max_px=512)
        ext_params["ref_image_url"] = f"data:image/jpeg;base64,{b64}"
        print(f"   [ref] Attached reference: {Path(ref_image_path).name}")

    payload = {
        "model": DOUBAO_MODEL,
        "platform": "volcengine",
        "extParams": ext_params,
    }

    print(f"   [doubao] Generating image ({width}x{height})...")
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    result = resp.json()

    # Extract image — could be URL or b64
    if result.get("data") and len(result["data"]) > 0:
        item = result["data"][0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        elif item.get("url"):
            img_resp = requests.get(item["url"], timeout=60)
            img_resp.raise_for_status()
            return img_resp.content

    raise RuntimeError(f"doubao returned no image data: {json.dumps(result, ensure_ascii=False)[:500]}")


# ─────────────────────────────────────────────────────────────
# Image generation: gemini (final composite)
# ─────────────────────────────────────────────────────────────

def generate_gemini_composite(api_key: str, prompt: str,
                              ref_images: list[tuple[str, bytes]] = None) -> bytes:
    """
    Generate composite image via gemini-3.1-flash-image-preview.
    ref_images: list of (label, image_bytes) tuples to include as reference.
    Returns raw image bytes.
    """
    url = f"{API_BASE_GEMINI}/api/v1/images/generate"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    ext_params = {
        "prompt": prompt,
        "size": "3:4",
    }

    # Attach reference images using the same format as generate_post.py
    if ref_images:
        image_list = []
        for label, img_bytes in ref_images:
            resized = resize_image_bytes(img_bytes, max_px=512)
            b64 = base64.b64encode(resized).decode()
            image_list.append(f"data:image/jpeg;base64,{b64}")
            print(f"   [ref] Attached: {label} ({len(b64)//1024} KB encoded)")
        ext_params["image"] = image_list
        ext_params["imageType"] = "image/jpeg"

    payload = {
        "model": GEMINI_MODEL,
        "platform": "google",
        "stream": True,
        "extParams": ext_params,
    }

    print(f"   [gemini] Generating composite...")
    resp = requests.post(url, headers=headers, json=payload, timeout=180, stream=True)
    resp.raise_for_status()

    # Parse response — handle both SSE stream and raw JSON
    raw_lines = []
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        raw_lines.append(line)

        # Try SSE format (data: {...})
        json_str = line
        if line.startswith("data:"):
            json_str = line[len("data:"):].strip()
            if json_str == "[DONE]":
                break

        # Try parsing as JSON
        try:
            chunk = json.loads(json_str)
            if chunk.get("data") and len(chunk["data"]) > 0:
                b64 = chunk["data"][0].get("b64_json")
                if b64:
                    return base64.b64decode(b64)
        except json.JSONDecodeError:
            continue

    # Debug: print what we got
    print(f"   [debug] Lines received: {len(raw_lines)}")
    for l in raw_lines[:3]:
        print(f"   [debug] {l[:200]}")
    raise RuntimeError("gemini returned no image data")


# ─────────────────────────────────────────────────────────────
# Scene interpretation via LLM
# ─────────────────────────────────────────────────────────────

def interpret_scene_for_character(api_key: str, group: str, text: str,
                                  character: str = "girl", feedback: str = None) -> str:
    """
    Call LLM to interpret the text + group and produce a concise visual scene
    description suitable for image generation.
    character: "girl" (purple-hair girl) or "mochi" (white fluffy ball)
    feedback: optional user feedback to adjust the scene description
    """
    if character == "girl":
        char_desc = "一个紫色头发、戴棕色眼镜的3D毛绒娃娃女孩"
        mood_guide = "场景应该带有讽刺意味，色调稍微阴郁、压抑，女孩的表情和肢体语言应该显得疲惫、无奈、心情不好。"
    else:
        char_desc = "一个白色圆滚滚的毛绒糯米团子（戴圆形墨镜）"
        mood_guide = "场景应该治愈、放松、轻松，糯米团子的表情和肢体语言应该显得悠闲、摆烂、无所谓的样子。"

    system_msg = (
        "你是一个视觉场景设计师。根据给定的文案和目标人群，"
        "为AI图像生成模型设计一个简短的视觉场景描述。"
        "描述应该具体、有画面感，适合3D毛绒风格的可爱插画。"
        "只输出场景描述，不要解释，不超过80字。"
    )
    user_msg = (
        f"角色：{char_desc}\n"
        f"目标人群：{group}\n"
        f"文案内容：{text}\n"
        f"情绪指导：{mood_guide}\n\n"
        f"请为这个角色设计一个符合文案情绪和人群特征的视觉场景。"
        f"描述角色在做什么、在什么环境中、什么表情和姿态。"
    )

    if feedback:
        user_msg += f"\n\n【用户反馈】请根据以下反馈调整场景描述：\n{feedback}"

    url = f"{API_BASE_DOUBAO}/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": "gemini-3.0-flash",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Handle different response formats
    if "choices" in data:
        return data["choices"][0]["message"]["content"].strip()
    elif "data" in data:
        # Some endpoints wrap in data
        return data["data"]["choices"][0]["message"]["content"].strip()
    else:
        raise RuntimeError(f"Unexpected LLM response format: {json.dumps(data, ensure_ascii=False)[:500]}")


# ─────────────────────────────────────────────────────────────
# Prompt builders
# ─────────────────────────────────────────────────────────────

def build_top_character_prompt(scene_desc: str) -> str:
    """Build prompt for the top character (purple-hair girl).
    scene_desc = LLM-interpreted visual scene description.
    """
    return (
        f"参考这张图里紫色头发、戴棕色眼镜的毛绒娃娃女孩角色的形象和3D毛绒画风，"
        f"生成一张她在新场景中的图片。"
        f"新场景：{scene_desc} "
        f"保持和参考图一致的3D毛绒质感、暖色调、柔和光线。图片中不要有任何文字。"
    )


def build_bottom_character_prompt(scene_desc: str) -> str:
    """Build prompt for the bottom character (white fluffy ball / Mochi).
    scene_desc = LLM-interpreted visual scene description.
    """
    return (
        f"参考这张图里白色圆滚滚的毛绒糯米团子角色（戴圆形墨镜）的形象和3D毛绒画风，"
        f"生成一张它在新场景中的图片。"
        f"新场景：{scene_desc} "
        f"保持和参考图一致的3D毛绒质感、柔和粉紫色调、温暖光线。图片中不要有任何文字。"
    )


def build_composite_prompt(scene_text: str, dissolver_text: str) -> str:
    """Build prompt for gemini to composite the final cover image.
    scene_text = 场景/黑话 (top bubble)
    dissolver_text = 封面：情绪消解文案 (bottom bubble)
    """
    return (
        f"参考第一张图的整体布局和排版风格，生成一张竖版封面图（3:4比例）。\n\n"
        f"布局要求：\n"
        f"上半部分：使用第二张参考图（紫发女孩角色）作为上半部分的画面，占约45%。\n"
        f"中间：一个白色圆角气泡，叠在上下两个画面之间，气泡内用粗体黑色字居中显示以下文字：\n"
        f"{scene_text}\n\n"
        f"下半部分：使用第三张参考图（白色糯米团子角色）作为下半部分的画面，占约45%。\n"
        f"底部：一个白色圆角气泡，气泡内用粗体黑色字居中显示以下文字：\n"
        f"{dissolver_text}\n\n"
        f"风格：白色气泡要有圆角，略微叠在画面边缘上。文字要大、清晰、易读。"
        f"整体风格可爱、温暖、略带幽默感。严格保持和第一张参考图一致的排版风格。"
    )


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mochi 情绪消解封面生成器")
    parser.add_argument("--md_file", default=DEFAULT_MD_FILE,
                        help="Path to topics_library.md")
    parser.add_argument("--output_dir", default=None,
                        help="Output directory (default: output/YYYY-MM-DD-dissolver)")
    parser.add_argument("--date", default=None,
                        help="Target date (default: today)")
    parser.add_argument("--index", type=int, default=0,
                        help="Which entry to use if multiple match the date (0-based)")
    parser.add_argument("--scene-only", action="store_true",
                        help="Only generate scene descriptions and save to file, don't generate images")
    parser.add_argument("--scene-file", default=None,
                        help="Load scene descriptions from file instead of generating new ones")
    parser.add_argument("--auto-confirm", action="store_true",
                        help="Skip scene confirmation and generate images directly")
    parser.add_argument("--api_key_path", default=DEFAULT_API_KEY_PATH,
                        help="Path to API key file (for LLM chat and doubao)")
    parser.add_argument("--api_key_abroad_path", default=DEFAULT_API_KEY_ABROAD_PATH,
                        help="Path to abroad API key file (for gemini)")
    parser.add_argument("--top_ref", default=None,
                        help="Override top character reference image path")
    parser.add_argument("--bottom_ref", default=None,
                        help="Override bottom character reference image path")
    args = parser.parse_args()

    # Resolve target date
    if args.date:
        target_date = args.date
    elif sys.platform == "win32":
        target_date = date.today().strftime("%Y/%#m/%#d")
    else:
        target_date = date.today().strftime("%Y/%-m/%-d")
    print(f"[*] Target date: {target_date}")

    # Load API keys
    api_key_domestic = read_api_key(args.api_key_path)
    api_key_abroad   = read_api_key(args.api_key_abroad_path)

    # Parse content
    entries = parse_dissolver_section(args.md_file, target_date)
    if args.index >= len(entries):
        print(f"[!] Only {len(entries)} entries found, using index 0")
        args.index = 0

    entry = entries[args.index]
    group          = entry["group"]
    scene          = entry["scene"]
    cover_text     = entry["cover_text"]
    dissolver_text = entry["dissolver_text"]

    # Bubble text mapping:
    #   top bubble (middle of image)    = scene (场景/黑话 column)
    #   bottom bubble                   = cover_text (封面：情绪消解文案 column)

    print(f"[*] Group: {group}")
    print(f"[*] Top bubble (黑话): {scene}")
    print(f"[*] Bottom bubble (消解): {cover_text}")
    print(f"[*] Entries for this date: {len(entries)} (using #{args.index})")

    # Output directory
    date_str = normalize_date(target_date)
    suffix = f"-dissolver-{args.index}" if len(entries) > 1 else "-dissolver"
    out_dir = Path(args.output_dir or f"{DEFAULT_OUTPUT_BASE}/{date_str}{suffix}")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] Output: {out_dir}\n")

    # Resolve reference image paths
    top_ref_path = args.top_ref or str(REFS_DIR / REF_TOP)
    bottom_ref_path = args.bottom_ref or str(REFS_DIR / REF_BOTTOM)

    # ── Step 0: Scene generation or loading ────────────────────
    scene_cache_file = out_dir / "scenes.json"

    if args.scene_file:
        # Load scenes from file
        print(f"[0/3] Loading scenes from {args.scene_file}...")
        import json
        with open(args.scene_file, 'r', encoding='utf-8') as f:
            scenes = json.load(f)
        top_scene_desc = scenes["top_scene"]
        bottom_scene_desc = scenes["bottom_scene"]
        print(f"   Top scene: {top_scene_desc}")
        print(f"   Bottom scene: {bottom_scene_desc}")
    else:
        # Generate new scenes
        print("[0/3] Interpreting scenes via LLM...")

        user_feedback = None
        while True:
            top_scene_desc = interpret_scene_for_character(
                api_key_domestic, group, scene, character="girl", feedback=user_feedback
            )
            bottom_scene_desc = interpret_scene_for_character(
                api_key_domestic, group, cover_text, character="mochi", feedback=user_feedback
            )

            print("\n" + "="*60)
            print("场景描述已生成，请确认：")
            print("="*60)
            print(f"\n【上半部分 - 紫发女孩场景】（讽刺/阴郁）")
            print(f"   {top_scene_desc}")
            print(f"\n【下半部分 - 白色糯米团子场景】（治愈/放松）")
            print(f"   {bottom_scene_desc}")
            print("\n" + "="*60)

            # Save scenes to file
            import json
            scenes_data = {
                "top_scene": top_scene_desc,
                "bottom_scene": bottom_scene_desc,
                "group": group,
                "scene_text": scene,
                "cover_text": cover_text
            }
            scene_cache_file.write_text(json.dumps(scenes_data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"\n[💾] 场景描述已保存到: {scene_cache_file}")

            if args.scene_only:
                print("\n[✓] --scene-only 模式，仅生成场景描述，不生图。")
                print(f"\n如需生图，请运行：")
                print(f"  python {__file__} --scene-file \"{scene_cache_file}\" --date \"{target_date}\" --index {args.index}")
                return

            if args.auto_confirm:
                print("\n[✓] Auto-confirm enabled, proceeding with image generation...")
                break

            user_input = input("\n输入 'y' 确认并继续生图 | 输入 'q' 退出 | 或直接输入反馈内容重新生成: ").strip()

            if user_input.lower() == 'y':
                print("[✓] 场景确认，开始生图...")
                break
            elif user_input.lower() == 'q':
                print("[!] 用户退出。")
                return
            elif user_input:
                # User provided feedback
                user_feedback = user_input
                print(f"[↻] 收到反馈，重新生成场景描述...\n")
                continue
            else:
                print("[!] 输入为空，请重新选择。")
                continue

    # ── Step 1: Generate top character image ───────────────────
    print("\n[1/3] Generating top character image (doubao)...")
    top_prompt = build_top_character_prompt(top_scene_desc)
    print(f"   Prompt: {top_prompt[:80]}...")
    top_bytes = generate_doubao_image(
        api_key_domestic, top_prompt,
        ref_image_path=top_ref_path if Path(top_ref_path).exists() else None,
        width=1024, height=1024,
    )
    top_path = out_dir / "top_character.jpg"
    top_path.write_bytes(top_bytes)
    print(f"   OK: top_character.jpg ({len(top_bytes)//1024} KB)")

    # ── Step 2: Generate bottom character image ────────────────
    print("\n[2/3] Generating bottom character image (doubao)...")
    bottom_prompt = build_bottom_character_prompt(bottom_scene_desc)
    print(f"   Prompt: {bottom_prompt[:80]}...")
    bottom_bytes = generate_doubao_image(
        api_key_domestic, bottom_prompt,
        ref_image_path=bottom_ref_path if Path(bottom_ref_path).exists() else None,
        width=1024, height=1024,
    )
    bottom_path = out_dir / "bottom_character.jpg"
    bottom_path.write_bytes(bottom_bytes)
    print(f"   OK: bottom_character.jpg ({len(bottom_bytes)//1024} KB)")

    # ── Step 3: Composite final cover via gemini ───────────────
    print("\n[3/3] Compositing final cover (gemini)...")
    composite_prompt = build_composite_prompt(
        scene_text=scene,           # middle bubble: 场景/黑话 column
        dissolver_text=cover_text,  # bottom bubble: 封面：情绪消解文案 column
    )

    ref_images = [
        ("cover_layout_ref", Path(str(REFS_DIR / REF_LAYOUT)).read_bytes()),
        ("top_character", top_bytes),
        ("bottom_character", bottom_bytes),
    ]
    composite_bytes = generate_gemini_composite(api_key_abroad, composite_prompt, ref_images)
    cover_path = out_dir / "cover.jpg"
    cover_path.write_bytes(composite_bytes)
    print(f"   OK: cover.jpg ({len(composite_bytes)//1024} KB)")

    # ── Save caption ───────────────────────────────────────────
    caption_path = out_dir / "caption.txt"
    caption_path.write_text(dissolver_text, encoding="utf-8")
    print(f"   OK: caption.txt")

    # ── Summary ────────────────────────────────────────────────
    print(f"\nDone! Output: {out_dir}")
    for f in sorted(out_dir.iterdir()):
        print(f"  {f.name:30s}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
