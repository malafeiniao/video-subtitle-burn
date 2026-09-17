# 环境准备

## 必需工具

- Python 3.10 或更新版本；只用标准库，无 requirements.txt 和 pip 依赖。
- FFmpeg 和 FFprobe；FFmpeg 需有 `ass` 滤镜（libass）、`libx264` 编码器、PNG 编码器、AAC 编码器及源文件对应的解码器。
- 静态 `.ttf` / `.otf` 字体；字体集合 `.ttc`、可变字体和网页字体不在脚本支持范围。使用字体发行方提供的静态版本。
- 足够的磁盘空间：压制时临时视频与其他成品会同时存在，不能保证固定体积比。

运行不需要网络、API Key、MCP、Apple 框架或另一个 Skill。首次安装工具和下载字体可能需要网络。

## 获取 FFmpeg

从 [FFmpeg 官方下载入口](https://ffmpeg.org/download.html) 选择对应平台的发行包。包名和版本不能保证包含字幕滤镜，安装后必须检测。

- **macOS**：可用 Homebrew 的含 libass 构建。`ffmpeg@7` 是一种候选，但升级依赖后旧安装可能失效；先执行二进制自身的 `-version`，再跑 doctor。版本化安装未加入 PATH 时用 `--ffmpeg` 指向实际可执行文件。
- **Windows**：解压包含 `ffmpeg.exe` 和 `ffprobe.exe` 的构建，把 `bin` 加入 PATH，或传完整路径。路径含空格时用引号。不要把 `.exe` 安装目录写进字幕滤镜字符串，脚本已通过临时工作目录处理路径。
- **Linux**：可使用发行版软件包，例如 Debian/Ubuntu 的 `ffmpeg`，再用 doctor 检查所安装构建的能力。

```sh
python scripts/burn_subtitles.py --doctor
python scripts/burn_subtitles.py --ffmpeg "/path/to/ffmpeg" --ffprobe "/path/to/ffprobe" --doctor
```

也可以配置环境变量 `SUBTITLE_FFMPEG`、`SUBTITLE_FFPROBE`；CLI 优先。未指定 FFprobe 时先找 FFmpeg 同目录下的程序，再找 PATH。

doctor 会实际列出滤镜和编码器，而不依赖 `ffmpeg -h filter=ass` 的退出码（一些构建即使滤镜不存在也返回 0）。它不证明所有源视频格式均可解码；用实际素材 `--check` 和样片继续验证。

## 字体

通过 `--font font.otf` 指定字体，重复参数可添加备用字体。脚本把字体复制到私有临时目录并传给 libass，**不要求系统安装**，也不使用固定的思源黑体名称。

中文可使用 [Adobe Source Han Sans](https://github.com/adobe-fonts/source-han-sans) 的静态 OTF 发行文件；其他语言应选择覆盖其文字的字体。字体许可随字体发行方提供，本仓库不附带字体。

脚本读取字体名称及 hhea 度量，字号按每个字体自身的度量换算。缺字时更换/增加覆盖字体；系统备用字体在不同机器上可能不同，因此需要查看 `.ffmpeg.log` / 报告里的实际字体选择，并检查画面。

## 常见问题

| 问题 | 处理 |
|---|---|
| `FFmpeg has no ass filter` | 换带 libass 的构建；仅有 libx264 不够 |
| FFmpeg 自身报 DLL/dylib 缺失 | 修复或重新安装完整的匹配构建；不要复制不兼容动态库冒充 |
| 字幕出现方框 | 添加覆盖该文字的字体，检查实际字体选择日志 |
| 两份字幕时间不一致 | 在字幕编辑器里人工核对并对齐，或提供已排好的双语 ASS |
| 复杂 VTT / 字幕标记被拒绝 | 转换成 ASS 并验证布局，脚本不会静默删掉样式 |
| `--audio copy` 失败 | 源音频可能不兼容 MP4，使用默认 `--audio aac` |
| 文件已经存在 | 使用新输出名；明确需要替换时才加 `--overwrite` |

FFmpeg 滤镜行为参考 [官方字幕滤镜文档](https://ffmpeg.org/ffmpeg-filters.html#ass)。
