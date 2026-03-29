# -*- coding: utf-8 -*-
"""
Mochi Xiaohongshu post generator.

Usage:
  python generate_post.py --md_file <path> [--output_dir <path>] [--date <YYYY/M/D>]

All three images are generated via gemini-3.1-flash-image-preview (abroad endpoint).
Each image uses a reference image + a targeted text-replacement prompt:
  Image 1 (cover.jpg)        : Replace hashtag tag & headline on cover_ref.png
  Image 2 (ui_screenshot.jpg): Replace notification title & user message on ui_ref.jpg
  Image 3 (mochi_reply.jpg)  : Replace body text on mochi_ref.png

Request format: stream=false, reference image passed as data URI in extParams.image array.
"""

import argparse
import base64
import json
import os
import re
import sys
from datetime import date
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

DEFAULT_API_KEY_ABROAD_PATH = "D:/Test/Mochi_test/api_key_abroad.txt"
DEFAULT_OUTPUT_BASE         = "D:/Test/Mochi_test/output"

REF_COVER = "cover_ref.png"
REF_UI    = "ui_ref.jpg"
REF_MOCHI = "mochi_ref.png"


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
    """Normalize date to YYYY-MM-DD (handles both 2026-03-11 and 2026/3/11)."""
    parts = re.split(r"[-/]", d.strip())
    if len(parts) == 3:
        try:
            y, m, day = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{y:04d}-{m:02d}-{day:02d}"
        except ValueError:
            pass
    return d.strip()


def parse_topics_library(md_file: str, target_date: str) -> dict:
    """
    Parse only the '## 1. 情绪碎片系列' table from topics_library.md.
    Returns fields needed for all three images.
    """
    with open(md_file, encoding="utf-8") as f:
        content = f.read()

    # Scope to section 1 only
    section_match = re.search(r"## 1\..+?(?=\n## \d+\.|\Z)", content, re.DOTALL)
    section_text = section_match.group(0) if section_match else content

    table_lines = [l.strip() for l in section_text.splitlines() if l.strip().startswith("|")]
    if len(table_lines) < 3:
        raise ValueError("No valid markdown table found in '情绪碎片系列' section")

    headers = [h.strip() for h in table_lines[0].split("|") if h.strip()]

    def find_col(*keywords):
        for kw in keywords:
            for i, h in enumerate(headers):
                if kw in h:
                    return i
        return None

    date_col      = find_col("更新日期")
    hashtag_col   = find_col("人群")
    theme_col     = find_col("主题", "情绪抓手")
    emotion_col   = find_col("用户心情")
    user_text_col = find_col("用户输入")
    reply_col     = find_col("Mochi 回复", "教练风格")

    if date_col is None:
        raise ValueError("Cannot find '更新日期' column in topics_library.md")

    def clean_cell(text: str) -> str:
        text = text.replace("<br><br>", "\n\n").replace("<br>", "\n")
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        return text.strip()

    def clean_theme(theme: str) -> str:
        """Strip internet-slang prefixes (e.g. 'md，', 'nnd，', '毁灭吧，') from theme text."""
        # Only remove specific slang prefixes, not all "text + comma" patterns
        slang_prefixes = [r"^md[，,]\s*", r"^nnd[，,]\s*", r"^毁灭吧[，,]\s*"]
        cleaned = theme.strip()
        for pattern in slang_prefixes:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        return cleaned

    norm_target = normalize_date(target_date)
    for row_line in table_lines[2:]:
        cells = [c.strip() for c in row_line.split("|") if c.strip()]
        if len(cells) <= date_col:
            continue
        if normalize_date(cells[date_col]) == norm_target:
            def get(col):
                return cells[col].strip() if col is not None and len(cells) > col else ""

            raw_hashtag  = get(hashtag_col)
            raw_theme    = get(theme_col)
            raw_emotion  = get(emotion_col)
            raw_usertext = get(user_text_col)
            raw_reply    = get(reply_col)

            hashtag     = f"#{raw_hashtag}" if raw_hashtag and not raw_hashtag.startswith("#") else raw_hashtag
            cover_text  = clean_theme(raw_theme)
            notif_title = raw_emotion.split("/")[0].strip() if "/" in raw_emotion else raw_emotion.strip()
            mochi_reply = clean_cell(raw_reply)

            return {
                "date":        cells[date_col],
                "hashtag":     hashtag or "#Mochi",
                "cover_text":  cover_text,
                "notif_title": notif_title,
                "user_text":   raw_usertext,
                "mochi_reply": mochi_reply,
            }

    raise ValueError(f"Date {target_date} (normalized: {norm_target}) not found in '情绪碎片系列'")


def img_to_data_uri(path: str, max_size_mb: float = 1.0):
    """
    Return (data_uri_string, mime_type) for a local image file.
    Compresses image to max_size_mb (in MB) while keeping original dimensions.
    """
    from PIL import Image
    from io import BytesIO

    suffix = Path(path).suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"

    # Load image
    img = Image.open(path)

    # Convert to bytes with quality compression
    max_bytes = int(max_size_mb * 1024 * 1024)
    buffer = BytesIO()
    img_format = "PNG" if suffix == ".png" else "JPEG"

    # For PNG, convert to JPEG for better compression
    if suffix == ".png":
        # Convert RGBA to RGB if needed
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = background
        img_format = "JPEG"
        mime = "image/jpeg"

    # Binary search for optimal quality
    quality = 95
    for _ in range(5):  # Max 5 iterations
        buffer.seek(0)
        buffer.truncate()
        img.save(buffer, format=img_format, quality=quality)
        size = buffer.tell()

        if size <= max_bytes:
            break

        # Reduce quality
        quality = int(quality * (max_bytes / size) * 0.9)
        quality = max(quality, 50)  # Don't go below 50

    img_bytes = buffer.getvalue()
    b64 = base64.b64encode(img_bytes).decode()
    return f"data:{mime};base64,{b64}", mime


def call_image_api(api_key: str, prompt: str, ref_path: str = None) -> bytes:
    """
    Call gemini-3.1-flash-image-preview with an optional reference image.
    Uses stream=false; reference image is passed as a data URI in extParams.image[].
    Returns raw image bytes from b64_json.
    """
    hdrs = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    ext = {"prompt": prompt, "size": "3:4"}

    if ref_path and os.path.exists(ref_path):
        data_uri, mime = img_to_data_uri(ref_path)
        ext["image"]     = [data_uri]
        ext["imageType"] = mime
        print(f"   [ref] {Path(ref_path).name}  ({len(data_uri)//1024} KB encoded)")

    resp = requests.post(
        f"{API_BASE_IMAGE}/api/v1/images/generate",
        headers=hdrs,
        json={
            "model":     IMAGE_MODEL,
            "platform":  "google",
            "stream":    False,
            "extParams": ext,
        },
        timeout=180,
        verify=False,
    )
    resp.raise_for_status()
    result = resp.json()

    code = result.get("code")
    if code and str(code) != "0":
        raise RuntimeError(f"Image API error code={code}: {result.get('message', '')}")

    b64_data = result["data"][0].get("b64_json")
    if not b64_data:
        raise RuntimeError(f"Image API returned no b64_json. Response keys: {list(result.keys())}")

    return base64.b64decode(b64_data)


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Generate Mochi Xiaohongshu post images.")
    parser.add_argument("--md_file",             default="D:/Test/Mochi_test/topics_library.md",
                        help="Path to topics_library.md")
    parser.add_argument("--output_dir",          default=None,
                        help="Output directory (default: output/YYYY-MM-DD)")
    parser.add_argument("--date",                default=None,
                        help="Target date YYYY/M/D (default: today)")
    parser.add_argument("--api_key_abroad_path", default=DEFAULT_API_KEY_ABROAD_PATH,
                        help="Path to abroad API key file")
    args = parser.parse_args()

    # Resolve target date
    if args.date:
        target_date = args.date
    elif sys.platform == "win32":
        target_date = date.today().strftime("%Y/%#m/%#d")
    else:
        target_date = date.today().strftime("%Y/%-m/%-d")
    print(f"[*] Target date: {target_date}")

    # Load API key and parse content row
    api_key = read_api_key(args.api_key_abroad_path)
    row = parse_topics_library(args.md_file, target_date)

    hashtag     = row["hashtag"]
    cover_text  = row["cover_text"]
    notif_title = row["notif_title"]
    user_text   = row["user_text"]
    mochi_reply = row["mochi_reply"]

    print(f"[*] 人群={hashtag}  封面={cover_text[:25]}...  通知={notif_title}")

    # Set up output directory
    out_dir = Path(args.output_dir or f"{DEFAULT_OUTPUT_BASE}/{date.today().strftime('%Y-%m-%d')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] Output: {out_dir}\n")

    # ── Image 1: Cover ────────────────────────────────────────
    print("[1/3] Generating cover image...")

    # Convert "comma + space" pattern to line breaks for multi-line display
    cover_text_formatted = cover_text.replace("， ", "，\n").replace(", ", ",\n")

    cover_prompt = (
        f"Keep all visual elements in the reference image exactly the same. "
        f"Only replace the rounded pill-tag text with '{hashtag}'. "
        f"Only replace the large Chinese headline text with the following text (preserve line breaks):\n{cover_text_formatted}\n"
        f"Display the headline text on multiple lines as shown above. "
        f"Do not alter background, glass jar illustration, '← 左滑看 Mochi 怎么回' footer, "
        f"sparkles, layout, colors, or any other element."
    )
    cover_bytes = call_image_api(api_key, cover_prompt, ref_path=str(REFS_DIR / REF_COVER))
    (out_dir / "cover.jpg").write_bytes(cover_bytes)
    print(f"   OK: cover.jpg  ({len(cover_bytes)//1024} KB)")

    # ── Image 2: UI Screenshot ────────────────────────────────
    print("\n[2/3] Generating UI screenshot...")
    ui_prompt = (
        f"Keep all visual elements in the reference image exactly the same. "
        f"Only replace the notification card title '心累' with '{notif_title}'. "
        f"Only replace the message body text with '{user_text}'. "
        f"Do not alter background blur, app chrome, card shape, button, layout, or any other element."
    )
    ui_bytes = call_image_api(api_key, ui_prompt, ref_path=str(REFS_DIR / REF_UI))
    (out_dir / "ui_screenshot.jpg").write_bytes(ui_bytes)
    print(f"   OK: ui_screenshot.jpg  ({len(ui_bytes)//1024} KB)")

    # ── Image 3: Mochi Reply Card ─────────────────────────────
    print("\n[3/3] Generating Mochi reply card...")
    mochi_prompt = (
        f"Keep all visual elements in the reference image exactly the same. "
        f"Only replace the body text inside the white card with the following text:\n{mochi_reply}\n"
        f"Do not alter background gradient, Mochi name label, avatar circle, "
        f"card shape, decorative diamond, or any other element."
    )
    mochi_bytes = call_image_api(api_key, mochi_prompt, ref_path=str(REFS_DIR / REF_MOCHI))
    (out_dir / "mochi_reply.jpg").write_bytes(mochi_bytes)
    print(f"   OK: mochi_reply.jpg  ({len(mochi_bytes)//1024} KB)")

    # ── Summary ───────────────────────────────────────────────
    print(f"\nDone! Output: {out_dir}")
    for f in sorted(out_dir.iterdir()):
        print(f"  {f.name:30s}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
