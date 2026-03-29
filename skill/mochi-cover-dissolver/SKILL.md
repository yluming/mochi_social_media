---
name: mochi-cover-dissolver
description: >
  Generate Mochi "情绪消解指南" cover images for Xiaohongshu. Use this skill when
  the user wants to create a 情绪消解 cover, generate dissolver covers, or produce
  the two-panel comic-style cover (top character + 黑话 bubble + bottom character + 消解 bubble).
  Trigger on any mention of "情绪消解", "消解封面", "dissolver cover", "Mochi翻译封面",
  or when the user asks to generate today's dissolver cover.
---

# Mochi 情绪消解封面生成

Generate a two-panel comic-style cover for the "Mochi翻译：情绪消解指南" series.

## 一句话运行

```bash
python D:/Test/Mochi_test/skill/mochi-cover-dissolver/scripts/generate_cover.py
```

无需参数，脚本自动读取今天日期并从 `topics_library.md` 的 `## 2. Mochi 翻译` 表格中匹配内容。

---

## 封面结构

```
┌─────────────────────────┐
│   上半部分：3D 毛绒女孩    │  ← doubao 生成 (top_ref.png 参考)
│   (紫发、眼镜、场景相关)    │
├─────────────────────────┤
│  ┌───────────────────┐  │
│  │ 🤐 场景/黑话 文案   │  │  ← 白色圆角气泡，取 "场景/黑话" 列
│  └───────────────────┘  │
├─────────────────────────┤
│   下半部分：白色毛绒球角色  │  ← doubao 生成 (bottom_ref.png 参考)
│   (墨镜、喝茶、轻松摆烂)   │
├─────────────────────────┤
│  ┌───────────────────┐  │
│  │ 😇 情绪消解文案     │  │  ← 白色圆角气泡，取 "封面：情绪消解文案" 列
│  └───────────────────┘  │
└─────────────────────────┘
```

---

## 输入来源

内容从 `D:/Test/Mochi_test/topics_library.md` 的 `## 2. Mochi 翻译：情绪消解指南` 表格读取：

| 列名 | 用途 |
|------|------|
| `人群` | 决定角色场景（大厂打工人/海外异乡人/科研搬砖人） |
| `场景/黑话` | 上半部分白色气泡文案 |
| `封面：情绪消解文案 (Cover)` | 下半部分白色气泡文案 |
| `正文` | 保存为 caption.txt |
| `更新日期` | 按日期匹配 |

同一日期可能有多条记录，脚本会为每条生成独立封面（用 `--index` 指定）。

---

## 生成流程

| 步骤 | 模型 | 端点 | 说明 |
|------|------|------|------|
| 1. 上半角色图 | `doubao-seedream-5-lite` | `https://imodel.xfinfr.com` | 根据人群生成场景 + top_ref 参考图 |
| 2. 下半角色图 | `doubao-seedream-5-lite` | `https://imodel.xfinfr.com` | 根据人群生成场景 + bottom_ref 参考图 |
| 3. 组装封面 | `gemini-3.1-flash-image-preview` | `https://imodel-ap1.iflyoversea.com` | 两张角色图 + 文字气泡 → 最终封面 |

---

## 输出

保存到 `D:/Test/Mochi_test/output/YYYY-MM-DD-dissolver/`：

- `top_character.jpg` — 上半角色底图
- `bottom_character.jpg` — 下半角色底图
- `cover.jpg` — 最终组装封面（1080×1440）
- `caption.txt` — 小红书正文配文

---

## API 配置

| 用途 | 端点 | 模型 | Key 文件 |
|------|------|------|----------|
| 角色底图生成 | `https://imodel.xfinfr.com` | `doubao-seedream-5-lite` | `api_key.env.txt` |
| 封面组装 | `https://imodel-ap1.iflyoversea.com` | `gemini-3.1-flash-image-preview` | `api_key_abroad.txt` |

---

## 参考图文件（references/）

| 文件 | 用途 |
|------|------|
| `top_ref.png` | 上半角色风格参考（紫发毛绒女孩） |
| `bottom_ref.png` | 下半角色风格参考（白色毛绒球） |

**用户需要将参考图放入 `references/` 目录后才能运行。**

---

## 可选参数

```bash
python generate_cover.py \
  --md_file "D:/path/to/topics_library.md" \
  --output_dir "D:/path/to/output" \
  --date "2026-03-18" \
  --index 0 \
  --top_ref "path/to/custom_top.png" \
  --bottom_ref "path/to/custom_bottom.png" \
  --api_key_path "..." \
  --api_key_abroad_path "..."
```
