# 巴菲特股东会问答音频流水线 — 产品需求文档 (PRD)

> **版本**: v1.0  
> **日期**: 2025-07-01  
> **状态**: 技术验证完成，待实施  
> **作者**: WorkBuddy 协助整理

---

## 一、背景

### 1.1 问题现状

用户在上下班通勤时收听伯克希尔·哈撒韦股东大会问答录音，当前通过喜马拉雅平台收听，存在以下痛点：

| 痛点 | 影响 |
|------|------|
| 播放过程中插入广告 | 打断收听节奏，体验差 |
| 翻译质量不高 | 某翻译版本表述生硬，投资逻辑传达不准确 |
| 无人声个性化 | 播音员朗读缺乏巴菲特本人的音色特征和感染力 |
| 缺少背景上下文 | 听到提及某公司/某事件时，缺少当时的市场背景和持仓信息 |

### 1.2 解决思路

利用大模型 + 开源 TTS 技术，构建一套自动化音频流水线：

```
英文原文 → LLM 翻译+背景增强 → GPT-SoVITS 音色克隆合成 → 无广告 MP3
```

### 1.3 用户环境

- **日常设备**: MacBook Air M3
- **GPU 设备**: Windows 主机（RTX 4070 Super 12GB），与 Mac 同一局域网
- **收听设备**: 手机（iPhone/Android）
- **协作工具**: WorkBuddy / Antigravity（跨设备继续开发）

---

## 二、目标

### 2.1 核心目标

1. **翻译质量提升**: 用大模型重新翻译，替代喜马拉雅的低质量翻译版本
2. **沉浸式收听**: 无广告打断，合成语音使用巴菲特本人音色
3. **背景增强**: 在问答中自动补充当时的市场环境、持仓情况等上下文
4. **音色可调**: 支持调整音色参数（更年轻、更清晰）

### 2.2 非目标（本期不做）

- 不做实时翻译/实时合成（离线批量处理即可）
- 不做多人对话音色区分（巴菲特+芒格不同音色）
- 不做自动内容更新推送（手动触发流水线）
- 不做移动端 App（产出 MP3 文件，用现有播放器收听）

---

## 三、用户故事

| 编号 | 角色 | 故事 | 优先级 |
|------|------|------|--------|
| US-01 | 收听者 | 作为收听者，我希望听到高质量的中文翻译，以便准确理解巴菲特的投资思路 | P0 |
| US-02 | 收听者 | 作为收听者，我希望语音使用巴菲特本人的音色，以便获得更沉浸的收听体验 | P0 |
| US-03 | 收听者 | 作为收听者，我希望在问答中插入背景信息，以便理解当时的市场环境和持仓情况 | P1 |
| US-04 | 收听者 | 作为收听者，我希望收听过程无广告打断 | P0 |
| US-05 | 收听者 | 作为收听者，我希望能调整音色（更年轻/更清晰），以适应个人偏好 | P2 |
| US-06 | 操作者 | 作为操作者，我希望在 Mac 上一键触发流水线，自动调用 Windows GPU 完成合成 | P0 |
| US-07 | 操作者 | 作为操作者，我希望产出 MP3 文件能方便地传到手机上 | P1 |

---

## 四、功能清单

### 4.1 功能模块概览

| 模块 | 功能 | 优先级 | 技术方案 | 所在设备 |
|------|------|--------|----------|----------|
| F1 | 内容获取 | P0 | Web scraping / 手动导入 | Mac |
| F2 | LLM 翻译 | P0 | DeepSeek / OpenAI API | Mac |
| F3 | 背景增强 | P1 | 同一 LLM 调用，Prompt 工程 | Mac |
| F4 | 文本分段 | P0 | Python 脚本，按问答切割 | Mac |
| F5 | 音色克隆 | P0 | GPT-SoVITS 零样本/few-shot | Windows |
| F6 | 语音合成 | P0 | GPT-SoVITS API 推理 | Windows |
| F7 | 音频拼接 | P0 | ffmpeg | Mac |
| F8 | 音色调参 | P2 | 参考音频预处理 + 推理参数 | Windows |
| F9 | 流水线编排 | P0 | Python 主控脚本 | Mac |
| F10 | 推送到手机 | P1 | AirDrop / iCloud / HTTP | Mac |

### 4.2 功能详细需求（EARS 规范）

#### F1: 内容获取

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F1-01 | Ubiquitous | The system shall accept English transcript text files as input, in plain text format. |
| F1-02 | Optional | Where the user provides a URL to a public transcript page, the system shall fetch and extract the text content. |
| F1-03 | Unwanted | If the input file is empty or unreadable, the system shall report an error and halt execution. |

**数据来源**:
- CNBC Warren Buffett Archive: https://buffett.cnbc.com/annual-meetings/
- Steady Compounding: https://steadycompounding.com/transcript/brk-2025/
- 雪球/知乎用户整理的英文 transcript

#### F2: LLM 翻译

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F2-01 | Ubiquitous | The system shall translate English Q&A transcripts into natural, colloquial Chinese using a large language model. |
| F2-02 | Event-driven | When the input text exceeds 4000 characters, the system shall split it into chunks and translate each chunk separately, preserving context across chunks. |
| F2-03 | Optional | Where the user specifies a different LLM provider (DeepSeek/OpenAI/local), the system shall use the specified provider and model. |
| F2-04 | Unwanted | If the LLM API call fails or times out, the system shall retry up to 3 times with exponential backoff, then report the error for that chunk and continue with remaining chunks. |
| F2-05 | State-driven | While a translation cache file exists for the input, the system shall prompt the user whether to reuse the cached result or re-translate. |

**翻译风格要求**:
- 口语化，保留巴菲特的幽默感
- 金融术语准确，公司名首次出现保留英文
- 明确区分提问者和回答者

#### F3: 背景增强

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F3-01 | Event-driven | When the translated text mentions a specific company stock, the system shall insert a background note with Berkshire's holding status at that time. |
| F3-02 | Event-driven | When the text involves macroeconomic judgments, the system shall insert a background note with the interest rate/inflation/market environment at that time. |
| F3-03 | Ubiquitous | The system shall limit background notes to at most 1-2 per Q&A pair to maintain listening flow. |
| F3-04 | Unwanted | If the LLM is uncertain about a background fact, the system shall omit the note rather than fabricate information. |

**背景补充标记格式**: `【📌 背景】补充内容`

#### F4: 文本分段

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F4-01 | Ubiquitous | The system shall split translated text into segments by Q&A pairs, delimited by `---`. |
| F4-02 | Event-driven | When a segment exceeds 500 characters, the system shall further split it for TTS processing to avoid synthesis timeout. |
| F4-03 | Optional | Where a segment is tagged with a role label (提问人/巴菲特/背景), the system shall preserve the role metadata for potential multi-voice synthesis. |

#### F5: 音色克隆

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F5-01 | Ubiquitous | The system shall use GPT-SoVITS for voice cloning, supporting both zero-shot (5s sample) and few-shot (1min sample) modes. |
| F5-02 | Event-driven | When the user provides a 5-15 second clean audio sample of Warren Buffett, the system shall perform zero-shot voice cloning without additional training. |
| F5-03 | Optional | Where the user provides 1-3 minutes of Buffett audio and triggers fine-tuning, the system shall train a few-shot model for improved similarity. |
| F5-04 | Unwanted | If the reference audio contains background noise or multiple speakers, the system shall warn the user and recommend using UVR5 for vocal isolation. |

**音频素材要求**:
- 格式: WAV, 16kHz, 单声道
- 时长: 零样本 5-15 秒 / 微调 1-3 分钟
- 质量: 纯人声，无背景音乐，无其他人说话

#### F6: 语音合成

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F6-01 | Ubiquitous | The system shall synthesize Chinese speech from translated text using the cloned Buffett voice model. |
| F6-02 | Event-driven | When the Mac pipeline script sends a segment to the Windows TTS API, the Windows host shall synthesize the audio and return the WAV file. |
| F6-03 | Unwanted | If a segment synthesis times out (>300s), the system shall skip that segment, log the error, and continue with remaining segments. |
| F6-04 | State-driven | While a synthesized audio file already exists for a segment, the system shall skip re-synthesis to support resumable processing. |

**TTS 推理参数（巴菲特风格建议）**:

| 参数 | 建议值 | 说明 |
|------|--------|------|
| text_lang | zh | 中文 |
| prompt_lang | en | 参考音频为英文 |
| top_k | 5 | 较小值，音色更稳定 |
| top_p | 0.8 | — |
| temperature | 0.8 | — |
| speed_factor | 0.85-0.95 | 巴菲特语速偏慢 |
| text_split_method | cut0 | 不自动切分 |

#### F7: 音频拼接

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F7-01 | Ubiquitous | The system shall merge all synthesized audio segments into a single MP3 file using ffmpeg. |
| F7-02 | Event-driven | When merging segments, the system shall insert 1.5 seconds of silence between segments for natural pacing. |
| F7-03 | Optional | Where the user specifies background music, the system shall mix it at low volume beneath the speech. |

#### F8: 音色调参

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F8-01 | Optional | Where the user requests a "younger/clearer" voice, the system shall apply pitch shifting (+1 to +3 semitones) to the reference audio before cloning. |
| F8-02 | Optional | Where the user specifies a speed factor, the system shall adjust the TTS speed_factor parameter accordingly. |

#### F9: 流水线编排

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F9-01 | Ubiquitous | The system shall provide a single-entry pipeline script that orchestrates: translate → split → synthesize → merge. |
| F9-02 | Event-driven | When any step fails, the system shall log the error, preserve completed work, and allow resumption from the failed step. |
| F9-03 | State-driven | While the Windows TTS service is unreachable, the system shall report the connection error and halt before the synthesis step. |
| F9-04 | Optional | Where the user passes `--skip-translate`, the system shall use existing translation cache and proceed directly to synthesis. |

#### F10: 推送到手机

| 编号 | 类型 | 需求描述 |
|------|------|----------|
| F10-01 | Optional | Where the user requests file transfer, the system shall support AirDrop (macOS), iCloud sync, or a temporary HTTP server for mobile download. |
| F10-02 | Event-driven | When the pipeline completes, the system shall output the file path and suggest transfer methods. |

---

## 五、流程说明

### 5.1 主流程

```
用户在 Mac 上执行 pipeline.py
         │
         ▼
┌─────────────────────┐
│  Step 1: 翻译+增强   │  Mac 本地 / 云端 LLM API
│  - 读取英文 transcript │
│  - 分段调用 LLM      │
│  - 翻译 + 背景补充    │
│  - 输出中文文本       │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 2: 文本分段    │  Mac 本地
│  - 按 Q&A 切割       │
│  - 标注角色          │
│  - 生成 TTS 输入列表  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 3: TTS 合成    │  Mac → Windows (HTTP API)
│  - 逐段发送到 Windows │
│  - GPT-SoVITS 推理    │
│  - 返回 WAV 音频      │
│  - 支持断点续传       │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Step 4: 拼接输出    │  Mac 本地
│  - ffmpeg 合并       │
│  - 插入静音间隔       │
│  - 输出 MP3          │
│  - 提示推送方式       │
└────────┬────────────┘
         │
         ▼
    最终 MP3 文件 → 手机
```

### 5.2 异常处理流程

| 异常场景 | 处理方式 |
|----------|----------|
| LLM API 超时/失败 | 重试 3 次，失败后跳过该段并记录 |
| Windows TTS 不可达 | 提示检查服务状态，暂停在合成步骤 |
| 单段合成超时 | 跳过该段，继续后续段落 |
| 磁盘空间不足 | 检查并提示 |
| 参考音频质量差 | 警告并建议预处理 |

---

## 六、交互说明

### 6.1 命令行界面

```bash
# 完整流水线
python pipeline.py input.txt --host 192.168.1.100 --ref-audio buffett_ref.wav

# 仅翻译
python translate.py input.txt --output translated.json

# 跳过翻译，直接合成
python pipeline.py input.txt --host 192.168.1.100 --skip-translate

# 自定义端口和输出名
python pipeline.py input.txt --host 192.168.1.100 --port 9880 --output buffett_2025.mp3
```

### 6.2 进度反馈

每个步骤执行时输出：
- 当前步骤名称和编号 (Step 1/4)
- 进度条 (段落数/总段数)
- 成功/失败状态
- 耗时统计

---

## 七、数据指标

### 7.1 质量指标

| 指标 | 目标 | 测量方式 |
|------|------|----------|
| 翻译准确率 | ≥ 95% | 人工抽检 10 段 |
| 音色相似度 | ≥ 85% | 主观评分 (1-5 分) |
| 背景信息准确率 | 100% (不编造) | 人工核实 |
| 合成成功率 | ≥ 95% | 成功段数/总段数 |
| 音频拼接无断裂 | 100% | 人工听检 |

### 7.2 性能指标

| 指标 | 目标 | 备注 |
|------|------|------|
| 翻译速度 | ≤ 30s/千字 | DeepSeek API |
| TTS 合成速度 (RTF) | ≤ 0.1 | 4070 Super 上 GPT-SoVITS |
| 单场股东会处理时间 | ≤ 30 分钟 | 约 5-8 万字 |
| 显存峰值 | ≤ 8 GB | 4070S 12GB 有余量 |

### 7.3 成本指标

| 项目 | 成本 |
|------|------|
| LLM 翻译 (DeepSeek) | ≈ ¥2-5/场 |
| GPT-SoVITS 本地推理 | 免费 (已有 GPU) |
| 音频素材 | 免费 (YouTube 公开资源) |
| **单场总成本** | **≈ ¥2-5** |

---

## 八、验收标准

### 8.1 功能验收

| 编号 | 验收项 | 验收标准 |
|------|--------|----------|
| AC-01 | 翻译功能 | 输入英文 transcript，输出通顺的中文翻译，金融术语准确 |
| AC-02 | 背景增强 | 翻译结果中包含 `【📌 背景】` 标记的背景补充，每段不超过 2 处 |
| AC-03 | 音色克隆 | 使用 5s 巴菲特参考音频，零样本合成中文语音，听感可辨识为巴菲特音色 |
| AC-04 | 远程调用 | Mac 通过 HTTP API 调用 Windows TTS 服务，成功接收 WAV 音频 |
| AC-05 | 端到端 | 从英文输入到 MP3 输出，一键完成，中间无需手动干预 |
| AC-06 | 断点续传 | 中断后重新运行，已完成的段落自动跳过 |
| AC-07 | 无广告 | 产出 MP3 无任何广告插入 |

### 8.2 非功能验收

| 编号 | 验收项 | 验收标准 |
|------|--------|----------|
| NFR-01 | 显存占用 | 峰值不超过 10GB (4070S 12GB) |
| NFR-02 | 处理时间 | 单场股东会 (约 5 万字) 端到端 ≤ 30 分钟 |
| NFR-03 | 跨平台 | Mac 端脚本在 macOS 14+ 上运行正常 |
| NFR-04 | 可维护性 | 代码有注释，配置项可调整，文档完整 |

---

## 九、待确认问题

| 编号 | 问题 | 影响 | 状态 |
|------|------|------|------|
| Q-01 | 翻译使用 DeepSeek 还是 OpenAI？ | 成本/质量 trade-off | 待用户确认 |
| Q-02 | 先处理哪一年的股东会内容？ | 决定首个验证样本 | 待用户确认 |
| Q-03 | 是否需要巴菲特+芒格双人音色？ | 影响复杂度 | 本期不做，后续迭代 |
| Q-04 | 音色年轻化/清晰化的具体程度？ | 影响参数调优 | 待实测后确认 |
| Q-05 | 是否需要 Web UI 界面？ | 影响开发量 | 本期命令行，后续可选 |

---

## 十、后续迭代方向

| 版本 | 功能 | 优先级 |
|------|------|--------|
| v1.1 | 多人音色（巴菲特 + 芒格 + 提问者） | P2 |
| v1.2 | Web UI 界面 (Gradio) | P2 |
| v1.3 | 自动内容更新监控（检测新 transcript 发布） | P3 |
| v1.4 | 播客 RSS 订阅源生成 | P3 |
| v2.0 | 实时翻译+合成（直播场景） | P3 |
