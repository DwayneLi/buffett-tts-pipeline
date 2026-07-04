# 🎙️ 巴菲特股东会问答音频流水线

> 用 AI 重新翻译 + 背景增强 + 巴菲特音色克隆，打造沉浸式股东会收听体验。

## 这是什么？

一套自动化流水线，将伯克希尔·哈撒韦股东大会的英文问答，转化为**高质量中文翻译 + 巴菲特音色语音合成**的无广告 MP3 音频。

**解决三个痛点**：
1. 喜马拉雅翻译质量不高 → 大模型重新翻译
2. 播音员朗读缺乏感染力 → 克隆巴菲特本人音色
3. 缺少背景上下文 → 自动补充持仓、市场环境等信息

## 架构一览

```
MacBook Air M3 (调度)  ──HTTP API──→  Windows 主机 4070S (GPU 推理)
     │                                    │
     ├─ LLM 翻译 + 背景增强               └─ GPT-SoVITS 音色克隆 + TTS
     ├─ 流水线编排
     ├─ 音频拼接 (ffmpeg)
     └─ 推送到手机
```

**技术栈**: Python · DeepSeek API · GPT-SoVITS · ffmpeg

## 快速开始

### 1. Windows 主机（一次性搭建）

```powershell
# 安装 Miniconda + Python 3.10
conda create -n gpt_sovits python=3.10 -y
conda activate gpt_sovits

# 安装 PyTorch (CUDA)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# 克隆并安装 GPT-SoVITS
git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS
pip install -r requirements.txt

# 启动 API 服务
python api_v2.py --port 9880
```

详见 [docs/部署指南.md](docs/部署指南.md)

### 2. Mac 端

```bash
# 安装依赖
pip3 install requests

# 设置 LLM API Key
export LLM_API_KEY=sk-your-deepseek-key

# 收集巴菲特参考音频（5-15 秒干净人声）
brew install yt-dlp ffmpeg
yt-dlp -f "bestaudio" --extract-audio --audio-format wav \
  --postprocessor-args "-ar 16000 -ac 1" \
  -o "buffett_ref.%(ext)s" "YouTube视频URL"

# 运行流水线
python scripts/pipeline.py input.txt --host <Windows-IP> --ref-audio <参考音频在Windows上的路径>
```

### 3. 收听

产出 MP3 文件 → AirDrop / iCloud → 手机播放

## 文档导航

| 文档 | 说明 | 给谁看 |
|------|------|--------|
| [docs/PRD.md](docs/PRD.md) | 产品需求文档（EARS 规范） | 产品/开发/设计 |
| [docs/架构设计.md](docs/架构设计.md) | 系统架构和技术选型 | 开发 |
| [docs/技术验证报告.md](docs/技术验证报告.md) | 技术可行性验证结果 | 决策者 |
| [docs/部署指南.md](docs/部署指南.md) | 分步部署操作指南 | 运维/开发 |

## 脚本说明

| 脚本 | 作用 | 运行位置 |
|------|------|----------|
| `scripts/translate.py` | LLM 翻译 + 背景增强 | Mac |
| `scripts/pipeline.py` | 端到端主控脚本 | Mac |
| `scripts/windows_tts_server_guide.py` | Windows TTS 服务启动指南 | Windows |

## 硬件要求

| 设备 | 配置 | 用途 |
|------|------|------|
| Windows 主机 | RTX 4070 Super 12GB + CUDA 12.4+ | GPT-SoVITS 训练和推理 |
| Mac | macOS 14+ (M3 或 Intel) | 翻译、流水线调度、音频拼接 |
| 网络 | 同一局域网 | Mac ↔ Windows 通信 |

## 当前状态

- [x] 需求规划
- [x] PRD 撰写
- [x] 技术选型验证
- [x] 架构设计
- [x] 核心脚本编写
- [ ] Windows 环境搭建（待执行）
- [ ] 巴菲特音频素材收集（待执行）
- [ ] 音色克隆效果验证（待执行）
- [ ] 端到端跑通（待执行）
- [ ] 参数调优（待执行）

## 跨设备继续开发

本项目的所有文档和脚本都在 GitHub 上。在任何电脑上：

```bash
git clone <repo-url>
cd buffett-tts-pipeline

# 用 WorkBuddy 或 Antigravity 打开项目
# 阅读 docs/PRD.md 了解需求
# 阅读 docs/部署指南.md 了解如何搭建环境
# 阅读 docs/架构设计.md 了解技术方案
```

## 许可证

MIT
