# 示例素材

本目录用于存放测试用的素材文件。

## 巴菲特参考音频

用于 GPT-SoVITS 音色克隆的参考音频片段。

### 要求

- 格式: WAV
- 采样率: 16kHz
- 声道: 单声道 (mono)
- 时长: 零样本 5-15 秒 / 微调 1-3 分钟
- 质量: 纯人声，无背景音乐，无其他人说话

### 获取方式

```bash
# 安装 yt-dlp
brew install yt-dlp ffmpeg

# 下载视频并提取音频
yt-dlp -f "bestaudio" --extract-audio --audio-format wav \
  --audio-quality 0 \
  --postprocessor-args "-ar 16000 -ac 1" \
  -o "buffett_%(title)s.%(ext)s" \
  "YouTube视频URL"

# 裁剪 10 秒干净片段
ffmpeg -i input.wav -ss 00:01:30 -t 10 -ar 16000 -ac 1 buffett_ref_10s.wav
```

### 推荐素材来源

| 来源 | 链接 |
|------|------|
| CNBC Buffett Archive | https://buffett.cnbc.com/ |
| Berkshire 年会视频 | YouTube 搜索 "Berkshire Hathaway Annual Meeting" |
| HBO 纪录片 | "Becoming Warren Buffett" |

## 测试文本

放置一小段股东会英文 transcript 用于端到端测试。

示例文件: `sample_transcript.txt`（可从 https://steadycompounding.com/transcript/brk-2025/ 获取）

> 注意: 参考音频和测试文本体积较大，不纳入 Git 管理，请参考 `.gitignore`。
