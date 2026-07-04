"""
巴菲特股东会音频流水线 — 主控脚本 (Mac 端)
串联：翻译 → 分段 → 远程 TTS 合成 → 音频拼接 → 输出

使用方法：
    python pipeline.py input.txt --host 192.168.1.100

前置条件：
    1. Windows 主机上已启动 GPT-SoVITS API 服务（python api_v2.py）
    2. 已设置 LLM_API_KEY 环境变量
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

# ============ 配置 ============
WINDOWS_API_PORT = 9880  # GPT-SoVITS API 默认端口
OUTPUT_DIR = "./output"


def check_prerequisites(args):
    """检查前置条件"""
    issues = []

    # 检查 LLM API Key
    if not os.environ.get("LLM_API_KEY"):
        issues.append("❌ 未设置 LLM_API_KEY 环境变量")

    # 检查 Windows 主机连通性
    if args.host:
        try:
            url = f"http://{args.host}:{WINDOWS_API_PORT}"
            resp = requests.get(f"{url}/status", timeout=5)
            if resp.status_code == 200:
                print(f"✅ Windows TTS 服务在线: {args.host}:{WINDOWS_API_PORT}")
            else:
                issues.append(f"⚠️  Windows TTS 服务响应异常: {resp.status_code}")
        except requests.ConnectionError:
            issues.append(f"❌ 无法连接 Windows TTS 服务 ({args.host}:{WINDOWS_API_PORT})，请确认已启动")
        except Exception as e:
            issues.append(f"❌ 连接 Windows 时出错: {e}")

    return issues


def step_translate(input_file: str) -> str:
    """Step 1: 翻译 + 背景增强"""
    print("\n" + "="*60)
    print("📝 Step 1/4: LLM 翻译 + 背景增强")
    print("="*60)

    output_json = f"{Path(input_file).stem}_translated.json"
    output_txt = f"{Path(input_file).stem}_translated.txt"

    # 检查是否已有缓存
    if os.path.exists(output_txt):
        print(f"📋 发现已有翻译缓存: {output_txt}")
        choice = input("   是否重新翻译？(y/N): ").strip().lower()
        if choice != "y":
            print("   使用缓存。")
            return output_txt

    # 调用翻译脚本
    script_dir = Path(__file__).parent
    translate_script = script_dir / "translate.py"

    cmd = [sys.executable, str(translate_script), input_file, "--output", output_json]
    print(f"🔄 执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)

    if result.returncode != 0:
        raise RuntimeError("翻译失败，请检查日志")

    return output_txt


def step_split_segments(translated_file: str) -> list[dict]:
    """Step 2: 将翻译结果拆分为 TTS 段落"""
    print("\n" + "="*60)
    print("✂️  Step 2/4: 拆分为 TTS 段落")
    print("="*60)

    with open(translated_file, "r", encoding="utf-8") as f:
        text = f.read()

    # 按 "---" 分隔
    raw_segments = re.split(r'\n---\n|\n---|\n={3,}\n', text)

    segments = []
    for i, seg in enumerate(raw_segments):
        seg = seg.strip()
        if not seg:
            continue

        # 提取角色标签（用于后续可能的多人音色）
        role = "buffett"  # 默认
        if "【提问人】" in seg or "【问题】" in seg:
            role = "narrator"
        if "【巴菲特回答】" in seg:
            role = "buffett"
        if "【📌 背景】" in seg:
            role = "background"

        segments.append({
            "id": i,
            "text": seg,
            "role": role,
            "char_count": len(seg),
        })

    print(f"   拆分为 {len(segments)} 个段落")
    for s in segments[:5]:  # 预览前 5 个
        print(f"   [{s['id']}] {s['role']:12s} | {s['char_count']:4d} 字 | {s['text'][:60]}...")
    if len(segments) > 5:
        print(f"   ... 还有 {len(segments) - 5} 段")

    return segments


def step_synthesize(segments: list[dict], host: str, ref_audio: str = None) -> list[str]:
    """Step 3: 远程调用 Windows GPT-SoVITS 合成语音"""
    print("\n" + "="*60)
    print("🎤 Step 3/4: 远程 TTS 语音合成")
    print("="*60)

    api_base = f"http://{host}:{WINDOWS_API_PORT}"

    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    audio_files = []
    total = len(segments)

    for i, seg in enumerate(segments):
        audio_file = os.path.join(OUTPUT_DIR, f"seg_{i:04d}.wav")

        # 跳过已合成的
        if os.path.exists(audio_file):
            print(f"   [{i+1}/{total}] ⏭️  已有缓存，跳过")
            audio_files.append(audio_file)
            continue

        print(f"   [{i+1}/{total}] 🎤 合成中... ({seg['char_count']} 字)")

        try:
            # GPT-SoVITS API v2 格式
            payload = {
                "text": seg["text"],
                "text_lang": "zh",  # 中文
                "ref_audio_path": ref_audio or "",  # 参考音频路径（在 Windows 上的路径）
                "prompt_lang": "en",  # 参考音频是英文
                "prompt_text": "",  # 参考音频对应的文本（可选）
                "top_k": 5,
                "top_p": 0.8,
                "temperature": 0.8,
                "text_split_method": "cut0",  # 不切分
                "batch_size": 1,
                "speed_factor": 1.0,
                "seed": -1,
            }

            resp = requests.post(f"{api_base}/tts", json=payload, timeout=300)
            resp.raise_for_status()

            # 保存音频
            with open(audio_file, "wb") as f:
                f.write(resp.content)

            audio_files.append(audio_file)
            print(f"        ✅ 已保存: {audio_file}")

        except requests.Timeout:
            print(f"        ❌ 超时（{seg['char_count']} 字可能太长）")
            audio_files.append(None)
        except Exception as e:
            print(f"        ❌ 合成失败: {e}")
            audio_files.append(None)

        # 小间隔，避免压垮 API
        time.sleep(0.5)

    success = sum(1 for f in audio_files if f is not None)
    print(f"\n   合成完成: {success}/{total} 成功")
    return audio_files


def step_merge(audio_files: list[str], output_name: str = None) -> str:
    """Step 4: 拼接音频 + 添加间隔"""
    print("\n" + "="*60)
    print("🔧 Step 4/4: 音频拼接")
    print("="*60)

    if output_name is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_name = f"buffett_qa_{timestamp}.mp3"

    output_path = os.path.join(OUTPUT_DIR, output_name)

    # 过滤掉失败的
    valid_files = [f for f in audio_files if f is not None and os.path.exists(f)]

    if not valid_files:
        raise RuntimeError("没有可用的音频文件进行拼接")

    # 生成 ffmpeg concat 文件列表
    concat_list = os.path.join(OUTPUT_DIR, "_concat_list.txt")
    with open(concat_list, "w") as f:
        for audio_file in valid_files:
            f.write(f"file '{os.path.abspath(audio_file)}'\n")
            # 在每个段落之间插入 1.5 秒静音
            f.write(f"file '{os.path.abspath(generate_silence(1.5))}'\n")

    # 用 ffmpeg 拼接
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list,
        "-codec:a", "libmp3lame",
        "-b:a", "128k",
        output_path
    ]

    print(f"🔄 拼接 {len(valid_files)} 个音频文件...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ 拼接失败: {result.stderr}")
        raise RuntimeError(f"ffmpeg 错误: {result.stderr}")

    # 清理
    os.remove(concat_list)

    # 获取文件大小
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"✅ 输出文件: {output_path} ({size_mb:.1f} MB)")

    return output_path


def generate_silence(duration_sec: float) -> str:
    """生成静音片段"""
    silence_file = os.path.join(OUTPUT_DIR, f"_silence_{duration_sec}s.wav")
    if not os.path.exists(silence_file):
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=16000:cl=mono",
            "-t", str(duration_sec),
            silence_file
        ], capture_output=True)
    return silence_file


def main():
    parser = argparse.ArgumentParser(description="巴菲特股东会音频流水线")
    parser.add_argument("input", help="英文 transcript 文本文件路径")
    parser.add_argument("--host", "-H", required=True, help="Windows 主机 IP 地址")
    parser.add_argument("--port", type=int, default=9880, help="GPT-SoVITS API 端口 (默认 9880)")
    parser.add_argument("--ref-audio", help="参考音频在 Windows 上的路径 (用于音色克隆)")
    parser.add_argument("--output", "-o", help="输出 MP3 文件名")
    parser.add_argument("--skip-translate", action="store_true", help="跳过翻译步骤（使用已有译文）")

    args = parser.parse_args()

    # 更新全局配置
    global WINDOWS_API_PORT
    WINDOWS_API_PORT = args.port

    print("="*60)
    print("🎙️  巴菲特股东会音频流水线")
    print("="*60)
    print(f"   Windows TTS 服务: {args.host}:{WINDOWS_API_PORT}")
    print(f"   输入文件: {args.input}")
    print()

    # 前置检查
    issues = check_prerequisites(args)
    if issues:
        for issue in issues:
            print(issue)
        if any("❌" in i for i in issues):
            print("\n请解决以上问题后重试。")
            return

    try:
        # Step 1: 翻译
        if args.skip_translate:
            translated_file = f"{Path(args.input).stem}_translated.txt"
            if not os.path.exists(translated_file):
                print(f"❌ 找不到译文文件: {translated_file}")
                return
            print(f"⏭️  跳过翻译，使用: {translated_file}")
        else:
            translated_file = step_translate(args.input)

        # Step 2: 分段
        segments = step_split_segments(translated_file)

        # Step 3: TTS 合成
        audio_files = step_synthesize(segments, args.host, args.ref_audio)

        # Step 4: 拼接
        output_path = step_merge(audio_files, args.output)

        print("\n" + "="*60)
        print("🎉 流水线完成！")
        print(f"📱 输出文件: {output_path}")
        print(f"💡 可通过以下方式推送到手机：")
        print(f"   • AirDrop 发送到 iPhone")
        print(f"   • 放入 iCloud 文件夹自动同步")
        print(f"   • python3 -m http.server 8080 （手机浏览器下载）")
        print("="*60)

    except Exception as e:
        print(f"\n❌ 流水线执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
