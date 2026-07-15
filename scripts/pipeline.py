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


def load_tts_config() -> dict:
    """读取仓库 config.json / config.example.json 的 tts 段（若存在）。"""
    candidates = [
        Path(__file__).resolve().parent.parent / "config" / "config.json",
        Path(__file__).resolve().parent.parent / "config" / "config.example.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("tts", {})
            except Exception:
                return {}
    return {}


def parse_transcript_header(filepath):
    """解析 transcript 文件头部元信息（# INTRO / # KEY_CHAPTERS）。"""
    info = {"intro": "", "key_chapters": []}
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("#"):
                break
            if line.startswith("# INTRO:"):
                info["intro"] = line[len("# INTRO:"):].strip()
            elif line.startswith("# KEY_CHAPTERS:"):
                nums = line[len("# KEY_CHAPTERS:"):].strip()
                info["key_chapters"] = [int(x) for x in nums.split(",") if x.strip()]
    return info


def filter_transcript(filepath, chapters=None, with_intro=False):
    """按章节筛选 transcript，可选加简介前缀。返回临时文件路径。"""
    info = parse_transcript_header(filepath)
    lines = open(filepath, encoding="utf-8").readlines()
    out = []

    # 加简介（作为旁白段，用 AUDIENCE MEMBER 让 LLM 归为提问人/旁白角色）
    if with_intro and info["intro"]:
        out.append(f"AUDIENCE MEMBER: {info['intro']}\n")

    if chapters:
        chapter_set = set(chapters)
        in_selected = False
        for line in lines:
            s = line.strip()
            ch_m = re.match(r'^#\s*CHAPTER:\s*(\d+)\.', s)
            if ch_m:
                in_selected = int(ch_m.group(1)) in chapter_set
                if in_selected:
                    out.append(line)
                continue
            if in_selected and s and not s.startswith("#"):
                out.append(line)
    else:
        for line in lines:
            s = line.strip()
            if s.startswith(("# MEETING", "# DATE", "# INTRO", "# KEY_CHAPTERS", "# KEY_CHAPTER_TITLES", "#   ")):
                continue
            out.append(line)

    import tempfile
    tmp = tempfile.NamedTemporaryFile("w", suffix="_filtered.txt", delete=False, encoding="utf-8", dir=".")
    tmp.writelines(out)
    tmp.close()
    return tmp.name


def check_prerequisites(args):
    """检查前置条件"""
    issues = []

    # 检查 LLM API Key（config.json 也可能提供，故仅警告不阻断）
    if not os.environ.get("LLM_API_KEY"):
        issues.append("⚠️  未设置 LLM_API_KEY 环境变量（若已在 config.json 的 llm.api_key 填好则无妨）")

    # 检查 Windows 主机连通性
    if args.host:
        try:
            url = f"http://{args.host}:{WINDOWS_API_PORT}"
            # 注意：GPT-SoVITS api_v2.py 默认没有 /status 端点，
            # 改为探测真实存在的 /docs（FastAPI 自动生成），仅判断"可达性"
            resp = requests.get(f"{url}/docs", timeout=5)
            # 2xx/3xx/401/404 都说明服务在跑（只是路由不同）；只有连不上才算 down
            if resp.status_code < 500:
                print(f"✅ Windows TTS 服务在线: {args.host}:{WINDOWS_API_PORT}")
            else:
                issues.append(f"⚠️  Windows TTS 服务响应异常: HTTP {resp.status_code}")
        except requests.ConnectionError:
            issues.append(f"❌ 无法连接 Windows TTS 服务 ({args.host}:{WINDOWS_API_PORT})，请确认已启动")
        except Exception as e:
            issues.append(f"❌ 连接 Windows 时出错: {e}")

    return issues


def step_translate(input_file: str, provider: str = None) -> str:
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
    if provider:
        cmd += ["--provider", provider]
    print(f"🔄 执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)

    if result.returncode != 0:
        raise RuntimeError("翻译失败，请检查日志")

    return output_txt


MAX_UTTERANCE_CHARS = 500  # PRD F4-02：单段超 500 字进一步切分，避免合成超时


def _map_role(label: str):
    """把【...】里的标签映射成角色。"""
    if "芒格" in label:
        return "munger"
    if "巴菲特" in label:
        return "buffett"
    if "背景" in label:
        return "background"
    if "提问" in label or "问题" in label:
        return "narrator"
    return None


def _split_long(text: str, max_chars: int = MAX_UTTERANCE_CHARS) -> list[str]:
    """超长段按句末标点切分，尽量不超过 max_chars（PRD F4-02）。"""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r'(?<=[。！？!?\n])', text)
    chunks, cur = [], ""
    for s in sentences:
        if not s:
            continue
        if len(cur) + len(s) <= max_chars:
            cur += s
        else:
            if cur:
                chunks.append(cur)
            cur = s
            while len(cur) > max_chars:  # 单句仍超长则硬切
                chunks.append(cur[:max_chars])
                cur = cur[max_chars:]
    if cur:
        chunks.append(cur)
    return chunks


def step_split_segments(translated_file: str) -> list[dict]:
    """Step 2: 把译文按角色标记拆成逐句 utterance，用于多音色合成。
    解析 【问题 N】【背景】【巴菲特】【芒格】 标记，每段发言单独成条；
    【问题 N】格式为"姓名提问：内容"，直接归入 narrator；超长段自动切分（PRD F4-02）。
    （背景段落默认复用 narrator 音色，可通过 ref_audio_paths.background 单独指定）
    """
    print("\n" + "="*60)
    print("✂️  Step 2/4: 按角色拆分为 TTS 段落")
    print("="*60)

    with open(translated_file, "r", encoding="utf-8") as f:
        text = f.read()

    utterances = []
    blocks = re.split(r'\n---\n|\n---|\n={3,}\n', text)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        parts = re.split(r'【([^】]+)】', block)
        if len(parts) == 1:
            # 无角色标记，整体当巴菲特
            for c in _split_long(block):
                utterances.append({"role": "buffett", "text": c, "char_count": len(c)})
            continue
        sections = {}  # role -> [content,...]
        for i in range(1, len(parts), 2):
            label = parts[i].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if not content:
                continue
            role = _map_role(label)
            if role:
                sections.setdefault(role, []).append(content)
        # narrator = 提问人 + 问题 合并
        narrator_text = " ".join(sections.get("narrator", [])).strip()
        if narrator_text:
            for c in _split_long(narrator_text):
                utterances.append({"role": "narrator", "text": c, "char_count": len(c)})
        for role in ("buffett", "munger"):
            for content in sections.get(role, []):
                for c in _split_long(content):
                    utterances.append({"role": role, "text": c, "char_count": len(c)})
        for content in sections.get("background", []):
            for c in _split_long(content):
                utterances.append({"role": "background", "text": c, "char_count": len(c)})

    for i, u in enumerate(utterances):
        u["id"] = i
    print(f"   拆分为 {len(utterances)} 个段落")
    from collections import Counter
    role_stat = Counter(u["role"] for u in utterances)
    print(f"   角色分布: {dict(role_stat)}")
    for s in utterances[:5]:
        print(f"   [{s['id']}] {s['role']:10s} | {s['char_count']:4d} 字 | {s['text'][:60]}...")
    if len(utterances) > 5:
        print(f"   ... 还有 {len(utterances) - 5} 段")

    return utterances


def step_synthesize(segments: list[dict], host: str, ref_map: dict, port: int = None) -> list[str]:
    """Step 3: 远程调用 Windows GPT-SoVITS 合成语音（按角色选参考音频，支持多音色）"""
    print("\n" + "="*60)
    print("🎤 Step 3/4: 远程 TTS 语音合成")
    print("="*60)

    port = port or WINDOWS_API_PORT
    api_base = f"http://{host}:{port}"

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

        ref = ref_map.get(seg["role"])
        if not ref:
            print(f"   [{i+1}/{total}] ⏭️  跳过 {seg['role']} 段（未配置参考音频）")
            audio_files.append(None)
            continue

        print(f"   [{i+1}/{total}] 🎤 {seg['role']} 合成中... ({seg['char_count']} 字)")

        try:
            # GPT-SoVITS API v2 格式
            payload = {
                "text": seg["text"],
                "text_lang": "zh",  # 中文
                "ref_audio_path": ref,  # 按角色选取的参考音频（Windows 上的路径）
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
    parser.add_argument("--host", "-H", default=None, help="Windows 主机 IP（也可在 config.json 的 tts.windows_host 填写）")
    parser.add_argument("--port", type=int, default=9880, help="GPT-SoVITS API 端口 (默认 9880，或取 config.json 的 tts.api_port)")
    parser.add_argument("--ref-audio", help="巴菲特参考音频路径（兼容旧用法；等价于 --ref-audio-buffett）")
    parser.add_argument("--ref-audio-buffett", help="巴菲特参考音频（Windows 路径），或取 config.json tts.ref_audio_paths.buffett")
    parser.add_argument("--ref-audio-munger", help="芒格参考音频（Windows 路径），或取 config.json tts.ref_audio_paths.munger")
    parser.add_argument("--ref-audio-narrator", help="提问人/旁白参考音频（Windows 路径），或取 config.json tts.ref_audio_paths.narrator")
    parser.add_argument("--output", "-o", help="输出 MP3 文件名")
    parser.add_argument("--skip-translate", action="store_true", help="跳过翻译步骤（使用已有译文）")
    parser.add_argument("--provider", default=None, choices=["deepseek", "glm", "qwen", "openai"],
                        help="LLM 服务商：deepseek / glm / qwen / openai（也可在 config.json 的 llm.provider 设置）")
    parser.add_argument("--chapters", default=None, help="只处理指定章节（逗号分隔编号，如 8,12,22）")
    parser.add_argument("--key-chapters", action="store_true", help="只处理 transcript 头部标记的 Key Chapters")
    parser.add_argument("--with-intro", action="store_true", help="在音频开头加入会议简介作为旁白")

    args = parser.parse_args()

    # 从 config.json 合并 tts 默认值（让用户在 config 里填的 IP / 端口 / 参考音频生效）
    tts_cfg = load_tts_config()
    if args.host is None:
        args.host = tts_cfg.get("windows_host")
    if args.port == 9880:
        args.port = tts_cfg.get("api_port", args.port)
    if args.ref_audio is None:
        args.ref_audio = tts_cfg.get("ref_audio_path")

    # 构建角色 → 参考音频 映射（多音色）。优先级：命令行 > config.ref_audio_paths > 单 ref 兜底
    ref_map = dict(tts_cfg.get("ref_audio_paths", {}))
    single_ref = args.ref_audio or tts_cfg.get("ref_audio_path")
    if single_ref and "buffett" not in ref_map:
        ref_map["buffett"] = single_ref
    if args.ref_audio_buffett:
        ref_map["buffett"] = args.ref_audio_buffett
    if args.ref_audio_munger:
        ref_map["munger"] = args.ref_audio_munger
    if args.ref_audio_narrator:
        ref_map["narrator"] = args.ref_audio_narrator
    # 背景默认复用 narrator 的参考音频
    if "background" not in ref_map and "narrator" in ref_map:
        ref_map["background"] = ref_map["narrator"]

    # 更新全局配置
    global WINDOWS_API_PORT
    WINDOWS_API_PORT = args.port

    if not args.host:
        print("❌ 未指定 Windows 主机 IP：请用 --host 192.168.x.x 或在 config.json 的 tts.windows_host 填写")
        return

    # 章节筛选（在翻译前过滤原始 transcript）
    actual_input = args.input
    filter_chap = None
    if args.key_chapters:
        hdr = parse_transcript_header(args.input)
        filter_chap = hdr["key_chapters"]
        if not filter_chap:
            print("⚠️  transcript 头部未找到 KEY_CHAPTERS，忽略 --key-chapters")
        else:
            print(f"📋 只处理 Key Chapters: {filter_chap}")
    elif args.chapters:
        filter_chap = [int(x.strip()) for x in args.chapters.split(",") if x.strip()]
        print(f"📋 只处理章节: {filter_chap}")

    if filter_chap or args.with_intro:
        if args.skip_translate:
            print("⚠️  --skip-translate 与章节筛选不兼容（需重新翻译筛选内容），忽略筛选")
        else:
            actual_input = filter_transcript(args.input, filter_chap, args.with_intro)
            print(f"📄 已生成筛选后输入: {actual_input}")
            if args.with_intro:
                print("   📝 已在开头加入会议简介作为旁白")

    print("="*60)
    print("🎙️  巴菲特股东会音频流水线")
    print("="*60)
    print(f"   Windows TTS 服务: {args.host}:{WINDOWS_API_PORT}")
    print(f"   输入文件: {actual_input}")
    if ref_map:
        print("   音色配置:")
        for r, p in ref_map.items():
            print(f"      - {r}: {p}")
    else:
        print("   ⚠️  未配置任何参考音频，合成步骤将全部跳过")
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
            translated_file = step_translate(actual_input, args.provider)

        # Step 2: 分段
        segments = step_split_segments(translated_file)

        # Step 3: TTS 合成
        audio_files = step_synthesize(segments, args.host, ref_map, WINDOWS_API_PORT)

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
