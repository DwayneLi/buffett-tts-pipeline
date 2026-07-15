# Windows 版：巴菲特音频素材收集指南

> 适用场景：你当前在 **Windows（RTX 4070S）** 上准备收集巴菲特参考音频。
> 原 `docs/部署指南.md` 第二步默认在 Mac 操作，这里给出 **Windows 等价步骤**，工具链一致（yt-dlp + ffmpeg），仅安装方式与命令引号不同。
> 对应 PRD：**F5 音色克隆**的素材要求（WAV / 16kHz / 单声道；零样本 5–15s，微调 1–3min；纯人声、无背景乐、无他人说话）。

---

## 0. 前置：安装工具（只需一次）

### 方案 A — 包管理器（推荐，自动配 PATH）
Win11 自带 `winget`；Win10 去 Microsoft Store 装 "App Installer" 即可。
以**管理员 PowerShell** 运行：

```powershell
winget install --id Gyan.FFmpeg -e
winget install --id Python.Python.3.11 -e   # 或你已有的 3.10
pip install yt-dlp
```

### 方案 B — 纯 pip（省去单独装 ffmpeg）
先装好 Python 3.10+（安装时勾选 **"Add to PATH"**），然后：

```powershell
pip install yt-dlp imageio-ffmpeg
```

> `imageio-ffmpeg` 会自带一个 ffmpeg，免去单独下载；但若后面 GPT-SoVITS 也要 ffmpeg，建议还是用方案 A 装独立版。

**验证安装：**
```powershell
yt-dlp --version
ffmpeg -version
```
两个都能打印版本号即 OK。

---

## 1. 建工作目录

```powershell
mkdir C:\buffett_audio
cd C:\buffett_audio
```

---

## 2. 选素材来源

| 来源 | 链接 | 特点 |
|------|------|------|
| CNBC Buffett Archive | https://buffett.cnbc.com/ | 最大巴菲特视频库（部分地区可直接访问）|
| 2025 股东会直播录像 | YouTube 搜 "Berkshire Hathaway 2025 Annual Meeting" | 5+ 小时素材 |
| HBO 纪录片《Becoming Warren Buffett》| YouTube | 高质量纯净人声 |
| 经典采访 | YouTube 搜 "Warren Buffett interview" | 丰富多样 |

> ⚠️ **网络提示**：YouTube 在国内通常需要代理 / 梯子；CNBC 站点一般可直接打开。若 `yt-dlp` 报连接错误，先确认代理已开、且当前终端能走代理（见文末"常见坑"）。

---

## 3. 下载 + 提取音频（统一转 16kHz 单声道 WAV）

**PowerShell（注意 `--postprocessor-args` 整体用双引号包住）：**
```powershell
yt-dlp -f "bestaudio" --extract-audio --audio-format wav --audio-quality 0 `
  --postprocessor-args "-ar 16000 -ac 1" `
  -o "C:\buffett_audio\buffett_%(title)s.%(ext)s" `
  "视频URL"
```

**CMD（同样命令，但 `%(...)` 要写成 `%%(...)`）：**
```cmd
yt-dlp -f bestaudio --extract-audio --audio-format wav --audio-quality 0 --postprocessor-args "-ar 16000 -ac 1" -o "C:\buffett_audio\buffett_%%(title)s.%%(ext)s" "视频URL"
```

产物：`C:\buffett_audio\buffett_xxx.wav`（已是 16kHz 单声道）。

---

## 4. 裁剪干净片段（给克隆用）

PRD F5 要求：5–15 秒零样本 / 1–3 分钟微调；**纯人声、无背景音乐、无其他人说话**。

从某段里截取 10 秒（例如从 1:30 开始）：
```powershell
ffmpeg -i C:\buffett_audio\buffett_xxx.wav -ss 00:01:30 -t 10 -ar 16000 -ac 1 C:\buffett_audio\buffett_clip_01.wav
```

**建议产出：**
- **3–5 段 5–15 秒干净片段** → 后面做首次零样本克隆验证立刻能用
- 有余力再拼 **1–3 分钟干净人声** → 留给 few-shot 微调

---

## 5.（可选，Windows GPU 优势）人声分离 UVR5

若原片带背景音乐 / 杂音，先用 **Ultimate Vocal Remover (UVR5)** 在本地 GPU 上分离人声，再裁剪。你这台 4070S 跑 UVR5 很快，对应 PRD **F5-04**（参考音频含噪 / 多人时，先 UVR5 再克隆）。

- 下载 UVR5（GitHub：`Anjok07/ultimate-rvc-voice-converter` 的 UVR 分支，或 standalone UVR）
- 选模型 `MRI-Voc_FT` 或 `Demucs`，输出人声后再走第 4 步裁剪

---

## 6. 收尾与下一步

- 把最终参考音频放到一个**稳定路径**，例如 `C:\audio\buffett_ref_10s.wav`，与 `config/config.example.json` 里的 `tts.ref_audio_path` 对齐。
- **后续**：在 Windows 上启动 GPT-SoVITS 做零样本 / 微调（见 `docs/部署指南.md` 第三步）；当你要用 Mac 远程调用 Windows TTS 时，再叫我帮你配 SSH / HTTP 调用。

---

## 常见坑

| 现象 | 原因 / 解决 |
|------|------------|
| `unable to find ffmpeg` | ffmpeg 不在 PATH；重装并确认 `ffmpeg -version` 能跑 |
| PowerShell 里 postprocessor 参数不生效 | `-ar 16000 -ac 1` 必须用**双引号整体包住** |
| CMD 里 `%(title)s` 变成空 | CMD 需写成 `%%(title)s` |
| yt-dlp 连接超时 / 403 | YouTube 需代理；确认终端走代理，或加 `--proxy "http://127.0.0.1:端口"` |
| 写入路径异常 | 输出 `-o` 路径尽量**英文、无空格**，避免中文路径/空格导致写入失败 |
| 人声里有背景乐 | 走第 5 步 UVR5 先分离 |

---

## 7. 已踩坑：`Fatal error in launcher: Unable to create process using '...python37...pip.exe'`

**现象**：直接敲 `pip install yt-dlp` 报此错，路径里指向一个旧 Python（如 `Python37`）的 `pip.exe`。

**原因**：`pip.exe` 是启动器，内部**写死**了要调用的 `python.exe` 路径。当那个 Python 被卸载/移动后，启动器拉不起进程 → `Unable to create process`（报错末尾的中文提示因控制台编码显示为 `?`，本质是"系统找不到指定的文件"）。

**解决（任选其一，都绕开坏 launcher）**：
```powershell
# 方案 A：模块形式，走当前真实可用的 python
python -m pip install yt-dlp

# 方案 B：用 py 启动器显式指定版本（装了 3.11 时）
py -3.11 -m pip install yt-dlp

# 方案 C：都不行就重装干净 Python（勾选 Add to PATH），再统一用 python -m pip
```

**预防**：永远优先用 `python -m pip ...` 或 `py -X.Y -m pip ...`，不要裸用 `pip`。那个老旧 Python（如 3.7）对 GPT-SoVITS 也没用，建议从"添加或删除程序"卸载，避免 PATH 里多个 python 互相打架。
