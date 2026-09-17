# video-subtitle-burn · 通用视频字幕压制 Skill

将已有字幕烧进视频画面，生成可以直接播放和分发的 MP4。适用于课程、访谈、产品介绍、社交媒体视频等，不绑定任何品牌。

[下载可安装 ZIP](https://github.com/malafeiniao/video-subtitle-burn/releases/latest) · [查看自动化测试](https://github.com/malafeiniao/video-subtitle-burn/actions)

**输入：** 视频 + 已校对字幕 + 字体。**输出：** H.264 MP4 + 可编辑 ASS + JSON 检查报告 + FFmpeg 日志。

- 单语 SRT、基础 WebVTT、已含双语的 SRT；也支持时间完全对应的两份字幕。
- 已有 ASS 保留样式与特效。
- 字体、字号、颜色、描边、边距及上下位置可配置；字体无需系统安装。
- 保留原文标点与时间轴，不会偷偷翻译、删标点或改断句。
- 样片、只检查、可选完整性校验、已有文件保护。
- Python 标准库实现，不需要 `pip install`、API Key、付费服务、Swift、OCR 或转录模型。

这不是自动听写或翻译工具。“通用”指品牌和字幕语言不受 TI 规范约束，并不意味着支持所有字幕格式、字体和特殊视频编码。

## 环境

1. Python **3.10+**。
2. 可运行的 **FFmpeg + FFprobe**，FFmpeg 包含 `ass` / libass、`libx264`，以及输入视频解码器、PNG 和 AAC 编码器。
3. 覆盖字幕字符的**静态 TTF / OTF 字体**。字体和 FFmpeg 不打包进本仓库。
4. 作为 Skill 使用时，AI 助手需能读取文件、运行本地命令、查看抽帧图片。也可以完全独立使用命令行脚本。

详见 [各平台安装与检测](references/setup.md)。跨平台代码不包含个人绝对路径；平台实际验证情况见 [验证记录](references/validation.md)。

## 安装 Skill

下载本仓库，解压后把整个目录命名为 `video-subtitle-burn`，放到你所用 AI 助手的 Skills 目录。保留 `SKILL.md`、`scripts/`、`references/` 和 `agents/` 的相对结构。

不同助手的安装位置由其自身配置决定。本包采用 `SKILL.md` 结构；`agents/openai.yaml` 是可选的 Codex 展示元数据，不影响独立运行。

对助手说：

> 使用 video-subtitle-burn，把这个视频和已校对的中英文 SRT 压成双语视频。中文在上，英文在下，先生成 10 秒样片检查效果，再生成完整视频。

## 命令行快速开始

在仓库目录中执行；macOS/Linux 常用 `python3`，Windows 常用 `py -3`，以下统一写 `python`。

```sh
python scripts/burn_subtitles.py --doctor

python scripts/burn_subtitles.py --video input.mp4 --subtitles captions.srt --font font.otf --output result.mp4 --check

python scripts/burn_subtitles.py --video input.mp4 --subtitles captions.srt --font font.otf --output sample.mp4 --preview 10

python scripts/burn_subtitles.py --video input.mp4 --subtitles zh.srt --secondary en.srt --font font.otf --output bilingual.mp4

python scripts/burn_subtitles.py --video input.mp4 --subtitles styled.ass --font font.otf --output styled.mp4
```

两份字幕的条数和每条起止时间必须完全一致，否则报错；不会按行号强行拼接。样片从指定时间开始截取，但字幕始终按原片时间轴渲染。ASS 时间精度为 10 ms，从 SRT/VTT 转换时单个边界最多舍入 5 ms。

脚本默认不覆盖已有文件，不修改原片和原字幕。`--check` 不写输出；实际压制输出四个同名前缀文件：`.mp4`、`.ass`、`.report.json`、`.ffmpeg.log`。

更多示例见 [使用说明](references/usage.md)；`examples/` 内有双语样例字幕，可与自制的至少 6 秒视频配合使用。

## 开发与分发

```sh
python -m unittest discover -s tests -v
python scripts/package_skill.py
```

第二条命令生成 `dist/video-subtitle-burn.zip`，包含运行所需文件和说明，不包含字体、媒体、Git 数据或缓存。字体及 FFmpeg 按各自许可另行获取。本仓库代码与说明使用 MIT License。
