---
name: mochi-story-series
description: >
  Generate a Mochi "healing storyboard" social media series.
  Inverse Workflow: Master Storyboard (3:4, text) -> 3 Cinematic Scenes (3:4, no text).
  Trigger on: "故事系列", "治愈剧场", "分镜", "generate story series".
---

# Mochi 治愈剧场系列生成 (先总后分版)

本 Skill 采用“先整体后局部”的生成逻辑：
1. **生成母版**：先由 AI 生成一张包含三格分镜和完整文案的 3:4 长图 (`storyboard.jpg`)。
2. **物理拆解**：脚本自动将长图裁剪为三个 9:4 的条带。
3. **AI 还原单图**：将条带交给 AI，扩充回 3:4 比例并**自动擦除文字**，得到干净的场景图 (`scene_1/2/3.jpg`)。

---

## 快速运行

```bash
python skill/mochi-story-series/scripts/generate_story.py \
  --content_file skill/mochi-story-series/content/episode_001.json
```

---

## 目录结构

与之前相同，但 `storyboard.jpg` 将作为第一个生成的文件。

- `references/`: ⚠️ 必须包含 `mochi_ref.png`, `style_ref.png`, `storyboard_ref.png`。
- `content/`: 存放剧本 JSON 文件。
- `output/`: 结果目录。

---

## JSON 剧本格式 (episode_XXX.json)

新版 JSON 更加简洁，专注于文案和整体氛围。

```json
[
  {
    "id": "001",
    "date": "2026-03-29",
    "story_theme": "整体故事氛围描述...",
    "storyboard_description": "详细描述三个分镜各自的内容...",
    "panels": [
      { "index": 1, "text": "第1格字幕...", "mochi_pos": "center" },
      { "index": 2, "text": "第2格字幕...", "mochi_pos": "bottom" },
      { "index": 3, "text": "第3格字幕...", "mochi_pos": "center" }
    ],
    "caption": "小红书正文..."
  }
]
```

---

## 注意事项

- **文字移除机制**：脚本会通过 Prompt 强制要求 AI 在还原单图时擦除文字。如果由于 API 随机性导致文字残留，可以尝试重新运行。
- **背景扩位**：由于单图是从窄条扩充回来的，背景的上下部分是 AI 脑补生成的，请确保长图生成时的构图合理。
