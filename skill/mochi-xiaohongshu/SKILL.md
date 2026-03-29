---
name: mochi-xiaohongshu
description: >
  Generate complete Xiaohongshu (小红书) posts for the Mochi app. Use this skill whenever
  the user wants to create a 小红书 post, generate Mochi content, produce the 3-image
  post format (cover + UI screenshot + Mochi reply card), or generate today's post from
  the topics library. Trigger on any mention of "小红书", "Mochi笔记", "生成帖子",
  "生成小红书", or when the user asks to generate today's post.
---

# Mochi 小红书笔记生成

Generate a complete 小红书 post for the Mochi app: **3 images + 1 caption**.

## 一句话运行

```bash
python D:/Test/Mochi_test/skill/mochi-xiaohongshu/scripts/generate_post.py
```

无需任何参数，脚本会自动读取今天日期并从 `topics_library.md` 中匹配内容。

---

## 输入来源

内容从 `D:/Test/Mochi_test/topics_library.md` 读取，表格结构如下：

| 人群 | 主题（情绪抓手）| 用户心情 | 用户输入 | Mochi 回复 (ICF 教练风格) | 小红书笔记文案 | 更新日期 |

脚本自动匹配今天日期（`更新日期` 列），取第一条匹配行，提取：
- `人群` → hashtag（自动加 `#`）
- `用户心情` → notif_title（取 `/` 前第一个词）
- `用户输入` → user_text
- `Mochi 回复 (ICF 教练风格)` → 图三卡片文字（**直接使用，不调用 AI**）
- `小红书笔记文案` → caption.txt（**直接使用，不调用 AI**）
- 笔记文案第一行粗体标题 → 封面文字

---

## 输出

保存到 `D:/Test/Mochi_test/output/YYYY-MM-DD/`：

- `cover.jpg` — 图一：封面（1080×1440）
- `ui_screenshot.jpg` — 图二：仿 UI 截图（1080×1440）
- `mochi_reply.jpg` — 图三：Mochi 回复卡（1080×1440）
- `caption.txt` — 小红书正文配文

---

## API 配置

| 用途 | 端点 | 模型 | Key 文件 |
|------|------|------|----------|
| 图像生成（3张图） | `https://imodel-ap1.iflyoversea.com` | `gemini-3.1-flash-image-preview` | `api_key_abroad.txt` |
| （对话接口备用） | `https://imodel.xfinfr.com` | `gemini-3.0-flash` | `api_key.env.txt` |

Key 文件格式：
```
api_key = 'sk-...'
```

### 图像生成接口调用要点

```
POST https://imodel-ap1.iflyoversea.com/api/v1/images/generate
Authorization: Bearer {api_key_abroad}
```

```json
{
  "model": "gemini-3.1-flash-image-preview",
  "platform": "google",
  "stream": true,
  "extParams": {
    "prompt": "...",
    "size": "3:4"
  }
}
```

- `stream: true` 必须传，否则无响应
- `size: "3:4"` 用字符串格式，不用 width/height
- 响应为 SSE 流，取第一行 JSON，从 `data[0].b64_json` 解码图片
- 参考图传入时先缩到最大 512px（避免 413），base64 编码后放在 `extParams.ref_image_url`

---

## 参考图文件（references/）

| 文件 | 用途 |
|------|------|
| `cover_ref.png` | 图一封面风格参考 |
| `ui_ref.jpg` | 图二 UI 截图参考 |
| `mochi_ref.png` | 图三 Mochi 回复卡参考 |
| `image_prompts.txt` | 图像生成 prompt（`COVER_PROMPT=`、`UI_PROMPT=`、`MOCHI_PROMPT=`） |

---

## 可选参数

```bash
python generate_post.py \
  --md_file "D:/path/to/topics_library.md" \   # 默认已配置
  --output_dir "D:/path/to/output" \            # 默认 output/YYYY-MM-DD
  --date "2026/3/11" \                          # 默认今天
  --api_key_path "..." \                        # 默认 api_key.env.txt
  --api_key_abroad_path "..."                   # 默认 api_key_abroad.txt
```
