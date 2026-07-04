"""
Windows 端 GPT-SoVITS API 服务启动指南

在 Windows 主机上运行此脚本，启动 API 服务供 Mac 远程调用。

============================================================
## 快速启动（推荐）

1. 打开 CMD 或 PowerShell
2. 激活环境：
   conda activate gpt_sovits
3. 进入 GPT-SoVITS 目录：
   cd C:\GPT-SoVITS
4. 启动 API 服务：
   python api_v2.py

默认端口: 9880
API 文档: http://localhost:9880/docs

============================================================
## 零样本推理调用示例（不训练，直接用参考音频克隆）

curl -X POST http://localhost:9880/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "我们持有大量苹果股票，因为我们相信这家公司的商业模式。",
    "text_lang": "zh",
    "ref_audio_path": "C:\\audio\\buffett_ref_10s.wav",
    "prompt_lang": "en",
    "prompt_text": "",
    "top_k": 5,
    "top_p": 0.8,
    "temperature": 0.8,
    "text_split_method": "cut0",
    "batch_size": 1,
    "speed_factor": 1.0
  }' --output test.wav

============================================================
## 参数调优指南

| 参数 | 作用 | 巴菲特风格建议 |
|------|------|---------------|
| speed_factor | 语速 | 0.85-0.95（巴菲特语速偏慢） |
| top_k | 采样多样性 | 5-15（越小越稳定） |
| temperature | 随机性 | 0.6-0.8（越小越稳定） |
| text_split_method | 切分方式 | "cut0" 不自动切分 |

## 音色调整技巧

要让巴菲特音色更"年轻/清晰"：
- 微调参考音频的音高（pitch shift +1~+3 semitones）
- 使用 Audacity 或 ffmpeg 预处理：
  ffmpeg -i buffett_ref.wav -af "asetrate=44100*1.03,aresample=44100" buffett_younger.wav

============================================================
## 防火墙设置

如果 Mac 无法访问 Windows 的 9880 端口：

1. 打开 Windows 防火墙设置
2. 新建入站规则 → 端口 → TCP → 9880
3. 允许连接

或直接用管理员 PowerShell：
   New-NetFirewallRule -DisplayName "GPT-SoVITS API" -Direction Inbound -Protocol TCP -LocalPort 9880 -Action Allow

============================================================
## 设置为开机自启（可选）

创建一个 run_tts_server.bat 放在启动文件夹：

   @echo off
   call C:\Users\你的用户名\miniconda3\Scripts\activate.bat gpt_sovits
   cd C:\GPT-SoVITS
   python api_v2.py --port 9880

然后将此 bat 文件放到：
   Win+R → shell:startup → 粘贴进去
"""

print(__doc__)
