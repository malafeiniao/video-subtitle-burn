---
name: video-subtitle-burn
description: 将已有时间戳的 SRT、基础 WebVTT 或 ASS 字幕烧录到视频，支持单语、同步双语、可配置字体样式、样片和批量交付。适用于硬字幕、压字幕、烧字幕、字幕嵌入画面和生成带字幕 MP4；不负责自动听写或翻译质量审核。
---

# 视频字幕压制

把用户提供的视频与已确认的字幕制作成硬字幕 MP4。独立于品牌，不需要 API、MCP、语音转录、OCR 或其他 Skill。所有处理在本地执行。

## 输入与边界

- 保留客户确认过的文字、标点、换行和时间关系，不默认重译、去标点、修正术语或重新估计时间轴。
- 单语：一份 UTF-8 SRT / 基础 WebVTT。双语：两份上述字幕，条数及每条起止毫秒必须一致，第一份在上、第二份在下；已经包含双语的单份 SRT 也可直接压制。
- 已有 ASS：保留作者的布局、特效、时间轴及重叠；CLI 的字号、颜色、位置选项只影响 SRT/VTT。额外字体通过重复 `--font` 传入。
- 双语时间不匹配时先报告具体差异，不擅自按行号拼接或拉伸时间。缺少译文时明确这需要翻译工作；不要把未经确认的翻译当客户原稿。
- 遇到 STYLE/REGION/定位 WebVTT、复杂字幕标记、HDR 或特殊交付编码，说明本脚本边界，依据用户需求使用适当转换流程，不静默扁平化样式或损失色彩。

## 执行

首次使用读 [环境准备](references/setup.md)，需要调整选项时读 [输入、样式与交付](references/usage.md)。脚本路径相对于本 Skill 目录；用户文件用绝对路径或当前工作目录下的路径。

1. 运行 `python scripts/burn_subtitles.py --doctor` 检测实际滤镜和编码器。选择覆盖字幕字符的静态 TTF/OTF 字体，读取真实画面尺寸。不要依赖固定的 FFmpeg 版本或本机路径。
2. 先以 `--check` 验证输入和双语对应关系。下载不完整、播放异常、字幕超出片尾等情况应使用 `--verify-media`；它检查数据覆盖和解码，不审核翻译。
3. 按用户要求配置样式；未指定时用白字黑描边、底部居中、保留标点和按字体度量换行。默认样式只是起点，没有通用的“中文必须单行”或“字号固定像素”要求。换行只改变显示，不改变 cue 时间边界。
4. 长片或批量任务先做具有代表性的 `--preview 10 --start 20` 样片，检查长句、多语言、明亮画面、画面关键内容遮挡和音画同步。只有用户要求确认样式时才等待确认；已有明确样式授权则自行验证后继续。
5. 完整压制后检查报告及实际画面。每种样式至少查看长句与亮背景的抽帧，检查原片有声音时成品仍有声音、时长正确、文字无缺字或裁切。脚本通过不等于视觉质量通过。
6. 交付 MP4、ASS、报告和渲染日志。ASS 是可编辑中间产物；原始 SRT/VTT 不改动。批量任务逐片探测并分配独立输出名，错误项停止处理并说明，不能把失败文件作为成品。

```sh
python scripts/burn_subtitles.py --video input.mp4 --subtitles captions.srt --font font.otf --output output.mp4 --check
python scripts/burn_subtitles.py --video input.mp4 --subtitles captions.srt --font font.otf --output sample.mp4 --preview 10
python scripts/burn_subtitles.py --video input.mp4 --subtitles captions.srt --font font.otf --output output.mp4
```

源文件不可被成品覆盖。输出已存在时优先换名字；只有用户已授权替换时才使用 `--overwrite`。字体选择、时间轴调整和翻译质量不应被自动检查结果替代。
