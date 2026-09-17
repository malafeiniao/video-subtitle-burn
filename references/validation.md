# 验证记录

## 本地验证 · 2026-09-17

环境：macOS / Apple Silicon、Python 3.14、FFmpeg 7.1.5（libass）、思源黑体 SC Medium 静态 OTF。

16 项测试全部通过，其中 9 项执行真实视频处理：

- SRT 与基础 WebVTT 解析、BOM/CRLF、中文标点及基本强调标签。
- 无效时间、重叠、复杂 VTT 样式、ASS 指令混入文本的错误提示。
- 双语时间边界严格匹配、ASS 百分秒舍入。
- 含空格、中文、方括号、逗号、单引号及冒号（非 Windows）的文件路径。
- 横屏带音频、竖屏无音频、带旋转元数据的视频。
- 从片中截取样片，字幕仍在正确时间出现。
- SRT → MP4、WebVTT → MP4、ASS 样式保留。
- 字体选择日志、实际烧进画面的文字像素、音频流保留、输出时长。
- 长中文换行不拆英文单词/型号、不改变原文和时间轴。
- 字体缺字会失败，已有视频即使授权覆盖也不会被失败渲染替换。
- 截断视频被拒绝；只检查模式不写交付文件；已有文件默认不覆盖。

此外实际生成并查看了 1280×720 亮背景中英双语样片和长句样片。测试发现原生 ASS 的中文换行依赖 libass 构建，因此加入字体前进宽度排版，再验证没有两侧裁切。

## 持续集成

仓库提供 `.github/workflows/test.yml`：

- Windows、macOS、Linux：Python 3.10 / 3.13 的纯 Python 测试与 ZIP 打包。
- Linux：安装 FFmpeg 与 DejaVu 字体，执行全套真实渲染测试。

2026-09-17 已在 GitHub Actions 的 Linux 环境完成 16 项测试（含真实压制）。首次 Windows 运行暴露了测试样例在文本模式下重复添加回车的问题，已改为按原始字节写入；命令行同时显式使用 UTF-8 输出，避免重定向时采用旧代码页。

GitHub 上各次实际运行结果以 Actions 为准。Windows 尚未在本地执行 FFmpeg 端到端渲染，不能把纯 Python 测试通过当成所有平台所有 FFmpeg 发行包均可用的保证。

## 复现

```sh
python -m unittest discover -s tests -v
```

未设置以下环境变量时，真实渲染测试会明确跳过。设置后重跑同一命令：

- `SUBTITLE_TEST_FFMPEG`：可运行、带 libass/libx264 的 FFmpeg 完整路径。
- `SUBTITLE_TEST_FONT`：静态 TTF/OTF 完整路径。

测试生成的是临时合成媒体，结束后自动清理；不需要客户素材。
