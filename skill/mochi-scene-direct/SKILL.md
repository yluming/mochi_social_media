---
name: mochi-scene-direct
description: >
  Generate Mochi "healing scenes" individually (3:4) for better layout and character visibility.
  Direct Workflow: JSON Script -> 3 Independent Cinematic Scenes (3:4, with text).
  Trigger on: "独立生成", "场景直出", "direct scene generation".
---

# Mochi 治愈剧场 - 场景直出版

此 Skill 采用“独立生成”逻辑，旨在解决长图分镜导致的角色过小和排版局促问题：
1. **独立生成**：根据 JSON 剧本，直接为每一格生成一张独立的 3:4 比例图片。
2. **优化排版**：通过 Prompt 精确控制 Mochi 和文字的相对位置，确保画面平衡且治愈。

---

## 运行命令

```bash
python skill/mochi-scene-direct/scripts/generate_scenes.py \
  --content_file skill/mochi-scene-direct/content/episode_006.json
```

---

## 目录结构

- `references/`: ⚠️ 必须包含 `mochi_ref.png`, `style_ref.png`, `storyboard_ref.png` (布局参考)。
- `content/`: 存放剧本 JSON 文件。
- `output/`: 结果目录（按日期分类）。

---

## 剧本格式 (episode_XXX.json)

```json
{
  "id": "006",
  "date": "2026-04-14",
  "story_theme": "故事背景描述...",
  "storyboard_description": "三格分镜的详细场景描述（用于控制画面）...",
  "panels": [
    { "index": 1, "text": "字幕 1", "mochi_pos": "lower-right" },
    { "index": 2, "text": "字幕 2", "mochi_pos": "center-left" },
    { "index": 3, "text": "字幕 3", "mochi_pos": "center" }
  ],
  "caption": "小红书正文..."
}
```

---

## 注意事项

- **独立请求**：每个场景都会发起一次独立的 API 请求，因此生成时间会比原版长。
- **构图控制**：如果 Mochi 位置不理想，可以在 `mochi_pos` 中尝试调整（如 `top`, `bottom`, `left`, `right`）。
