# -*- coding: utf-8 -*-
"""
imodel Gemini 图像生成调用脚本

Usage:
  python call_gemini.py "你的prompt" [--ref img1.png img2.png] [--size 3:4] [--output result.jpg]
"""

import argparse
import base64
import json
import re
import sys
import time
from io import BytesIO
from pathlib import Path

import requests

API_BASE = "https://imodel-ap1.iflyoversea.com"
MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_KEY_PATH = "D:/Test/Mochi_test/api_key_abroad.txt"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", buffering=1)


def read_api_key(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        m = re.search(r"['\"](.+?)['\"]", f.read())
    if not m:
        raise ValueError(f"Cannot parse API key from: {path}")
    return m.group(1)


def resize_image(img_bytes: bytes, max_px: int = 512) -> bytes:
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


def generate(api_key: str, prompt: str, ref_paths: list[str] = None,
             size: str = "3:4") -> bytes:
    ext_params = {"prompt": prompt, "size": size}

    if ref_paths:
        image_list = []
        for p in ref_paths:
            raw = Path(p).read_bytes()
            resized = resize_image(raw, max_px=512)
            b64 = base64.b64encode(resized).decode()
            image_list.append(f"data:image/jpeg;base64,{b64}")
            print(f"  [ref] {Path(p).name} ({len(b64)//1024} KB encoded)")
        ext_params["image"] = image_list
        ext_params["imageType"] = "image/jpeg"

    payload = {
        "model": MODEL,
        "platform": "google",
        "stream": True,
        "extParams": ext_params,
    }

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        print(f"  [*] Calling {MODEL} (attempt {attempt}/{max_retries})...")
        resp = requests.post(
            f"{API_BASE}/api/v1/images/generate",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
            json=payload, timeout=300, stream=True,
        )
        resp.raise_for_status()

        raw_lines = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            raw_lines.append(line)
            json_str = line[len("data:"):].strip() if line.startswith("data:") else line
            if json_str == "[DONE]":
                break
            try:
                chunk = json.loads(json_str)
                # Check for 429 rate limit
                if chunk.get("code") == "10006" and "429" in chunk.get("message", ""):
                    wait = 15 * attempt
                    print(f"  [!] Rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    break
                if chunk.get("data") and len(chunk["data"]) > 0:
                    b64 = chunk["data"][0].get("b64_json")
                    if b64:
                        return base64.b64decode(b64)
            except json.JSONDecodeError:
                continue
        else:
            # Loop finished without break (no 429), but no image either
            print(f"  [debug] Lines received: {len(raw_lines)}")
            for l in raw_lines[:5]:
                print(f"  [debug] {l[:300]}")
            raise RuntimeError("No image data returned")

    raise RuntimeError("Max retries exceeded (rate limited)")


def main():
    parser = argparse.ArgumentParser(description="imodel Gemini 图像生成")
    parser.add_argument("prompt", help="生成图像的 prompt")
    parser.add_argument("--ref", nargs="+", default=[], help="参考图路径（可多张）")
    parser.add_argument("--size", default="3:4", help="图像比例 (default: 3:4)")
    parser.add_argument("--output", "-o", default=None, help="输出文件路径")
    parser.add_argument("--key", default=DEFAULT_KEY_PATH, help="API key 文件路径")
    args = parser.parse_args()

    api_key = read_api_key(args.key)
    t0 = time.time()
    img_bytes = generate(api_key, args.prompt, args.ref, args.size)
    elapsed = time.time() - t0

    out_path = args.output or f"gemini_output_{int(time.time())}.jpg"
    Path(out_path).write_bytes(img_bytes)
    print(f"  [OK] {out_path} ({len(img_bytes)//1024} KB, {elapsed:.1f}s)")


if __name__ == "__main__":
    main()
