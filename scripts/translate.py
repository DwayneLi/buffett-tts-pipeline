"""
巴菲特股东会问答 — 翻译 + 背景增强脚本
使用 DeepSeek API 进行翻译，可替换为 OpenAI / 本地模型

使用方法：
    python translate.py input.txt --output output.json
    python translate.py input.txt --provider glm     # 切换到智谱 GLM
    python translate.py input.txt --provider qwen     # 切换到通义千问
（也可不改命令行，直接在 config.json 的 llm.provider 填 glm / qwen / deepseek）

输入：英文 transcript 文本文件
输出：带翻译和背景补充的 JSON 文件
"""

import argparse
import json
import os
import re
import time
import requests
from pathlib import Path

# ============ 重试配置（PRD F2-04）============
MAX_RETRIES = 3          # 最多重试 3 次
BACKOFF_BASE = 2.0       # 指数退避基数（秒）：2, 4, 8...

# ============ 配置 ============
# Provider 注册表：一行切换 GLM / 千问 / DeepSeek / OpenAI 兼容
PROVIDERS = {
    "deepseek": {"label": "DeepSeek", "api_url": "https://api.deepseek.com/chat/completions", "model": "deepseek-chat"},
    "glm":      {"label": "智谱 GLM", "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-4-flash"},
    "qwen":     {"label": "通义千问", "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "model": "qwen-plus"},
    "openai":   {"label": "OpenAI",   "api_url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o-mini"},
}

# 运行时配置（在 main 中按 命令行 > 环境变量 > config.json > 注册表 合并）
API_CONFIG = {}


def load_llm_config() -> dict:
    """读取仓库 config.json / config.example.json 的 llm 段（若存在）。"""
    candidates = [
        Path(__file__).resolve().parent.parent / "config" / "config.json",
        Path(__file__).resolve().parent.parent / "config" / "config.example.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("llm", {})
            except Exception:
                return {}
    return {}


def build_api_config(args) -> dict:
    """合并优先级：
    provider = 命令行 --provider > 环境变量 LLM_PROVIDER > config.json > deepseek
    api_url/model = 环境变量 > 注册表(对应 provider) > config.json(兜底，主要给未知/自定义 provider)
    api_key = 命令行 --api-key > 环境变量 LLM_API_KEY > config.json > 占位符
    说明：已知 provider 的端点以注册表为准，切换 provider 即切换端点；config.json 的
    api_url/model 只在 provider 不在注册表（自定义）时才生效。
    """
    cfg = load_llm_config()
    provider = args.provider or os.environ.get("LLM_PROVIDER") or cfg.get("provider") or "deepseek"
    entry = PROVIDERS.get(provider, {})

    api_url = os.environ.get("LLM_API_URL") or entry.get("api_url") or cfg.get("api_url")
    model = os.environ.get("LLM_MODEL") or entry.get("model") or cfg.get("model")
    api_key = args.api_key or os.environ.get("LLM_API_KEY") or cfg.get("api_key") or "your-api-key-here"
    return {
        "provider": provider,
        "label": entry.get("label", provider),
        "api_url": api_url,
        "model": model,
        "api_key": api_key,
    }


SYSTEM_PROMPT = """你是一位精通巴菲特投资哲学和伯克希尔·哈撒韦历史的翻译专家。

## 任务
将伯克希尔·哈撒韦股东大会的英文问答翻译成地道的中文，并适当补充背景信息。
**必须保留发言者角色**：原文里巴菲特(Warren Buffett)和芒格(Charlie Munger)的发言要分别标注，不要混并。

## 翻译要求
1. **口语化**：翻译要像自然的中文对话，不要翻译腔。保留巴菲特/芒格的幽默与智慧。
2. **准确性**：金融术语、公司名称、数据必须准确。
3. **角色标注**：每段发言用对应标记，只输出实际有发言的角色。
4. **术语简称一致性**：
   - 公司名/人名**首次出现**时，用"中文名（English Name，简称XXX）"格式建立对照，如"精密铸件公司（Precision Castparts，简称PCP）"。
   - **后续出现时**：如原文用全称，译为中文名（如"精密铸件公司"）；如原文用简称，保持简称（如"PCP"）。不要重复给出英文原名或重复解释。
   - 人名同理：首次"CEO马克·多纳根（Mark Donegan）"，后续直接用"马克"。
   - 如果文前已提供术语对照表，严格遵循表中的简称。

## 背景补充规则
在以下情况，插入【背景】补充信息（每段问答最多 1-2 处）：
- 提到某家公司的投资时 → 补充当时伯克希尔的持仓情况、交易内容
- 涉及宏观经济判断时 → 补充当时的利率/通胀/市场环境
- 巴菲特的经典比喻或反复出现的主题 → 补充他过往的相关论述
- 事件有重要后续发展 → 简要补充（如"注：此后XXX"），包括后续几年间公司的业绩验证
- 背景信息不超过 3 句话，不确定则省略，绝不编造

## 输出格式（每个问答之间用 --- 分隔）
【提问人】姓名（来自XXX机构）
【问题】中文翻译
【背景】背景补充内容（如有，放在问题之后、回答之前）
【巴菲特】巴菲特的中文回答（如该轮他发言）
【芒格】芒格的中文回答（如该轮他发言）
---

注意：
- 某轮若只有巴菲特回答，就只输出【巴菲特】；只有芒格就只输出【芒格】；两人都答就各输出一段。
- 【背景】放在【问题】之后、【巴菲特】/【芒格】之前，让听众先了解背景再听回答。
- 不要过度补充背景，保持问答流畅节奏。
"""


def build_user_prompt(text: str, glossary: list[str] = None) -> str:
    """构建用户消息，可选附带术语对照表以保持跨 chunk 一致性。"""
    prompt = "请翻译以下伯克希尔·哈撒韦股东大会问答：\n\n"
    if glossary:
        prompt += "【已建立的术语对照表】（后续翻译请严格遵循这些简称，不要重复给出英文原名或重复解释）\n"
        prompt += "\n".join(glossary) + "\n\n"
    prompt += text
    return prompt


def extract_glossary(translated_text: str) -> list[str]:
    """从译文中提取已建立的术语对照（中文名（English，简称XXX）格式）。"""
    entries = []
    seen = set()
    # 找所有 （English Name，简称XXX） 或 （English Name） 模式
    for m in re.finditer(r'（([A-Za-z][A-Za-z .\-=]+?)(?:，简称([A-Za-z]+))?）', translated_text):
        en = m.group(1).strip()
        abbr = m.group(2) or ""
        key = en.lower()
        if key in seen:
            continue
        seen.add(key)
        # 往前找中文名（括号前最后 2-6 个汉字）
        before = translated_text[max(0, m.start() - 20):m.start()]
        cn_match = re.search(r'([\u4e00-\u9fa5·]{2,6})$', before)
        cn = cn_match.group(1) if cn_match else ""
        # 去掉常见单字前缀（介词/连词/动词等）
        cn = re.sub(r'^(于|关于|对于|的|是|了|在|为|对|由|和|与|及|有|被|将|已|还|也|又|都|就|才|只|会|能|可|应|要|想|说|问|答|来|去|到|从|给|让|把|叫|请|或|这|那|其|该|某|名为|叫|称)', '', cn)
        if cn:
            entry = f"- {en} → {cn}" + (f"（简称{abbr}）" if abbr else "")
        else:
            entry = f"- {en}" + (f"（简称{abbr}）" if abbr else "")
        entries.append(entry)
    return entries


def call_llm(system_prompt: str, user_prompt: str) -> str:
    """调用 LLM API"""
    headers = {
        "Authorization": f"Bearer {API_CONFIG['api_key']}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": API_CONFIG["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    print(f"📡 正在调用 {API_CONFIG['label']} API ({API_CONFIG['model']})...")

    response = None
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(API_CONFIG["api_url"], headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            break  # 成功，退出重试循环
        except (requests.RequestException, requests.Timeout) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE ** attempt  # 2s, 4s, 8s ...
                print(f"   ⚠️  第 {attempt} 次调用失败（{e}），{wait:.0f}s 后重试...")
                time.sleep(wait)
            else:
                print(f"   ❌ 重试 {MAX_RETRIES} 次仍失败: {e}")

    if response is None:
        raise last_err or RuntimeError("LLM 调用失败")
    response.raise_for_status()

    data = response.json()
    content = data["choices"][0]["message"]["content"]

    # 打印 token 用量
    usage = data.get("usage", {})
    if usage:
        print(f"   Tokens: 输入 {usage.get('prompt_tokens', '?')} / 输出 {usage.get('completion_tokens', '?')}")

    return content


def split_transcript(text: str, max_chunk_chars: int = 4000) -> list[str]:
    """
    将长 transcript 切分，确保每段不超过 max_chunk_chars（PRD F2-02）。
    策略：优先按 Question/Q 切 → 按空行切 → 按单行切（行式 transcript）→ 合并短段。
    """
    # 1) 先尝试按 "Question:" 或 "Q:" 切分
    qa_pattern = r'(?=(?:Question|Q|QUESTION)(?:\s*\d+)?[:\n])'
    chunks = re.split(qa_pattern, text)

    # 2) 若切不出来（非标准格式），按空行切
    if len(chunks) <= 2:
        chunks = re.split(r'\n\n+', text)

    # 3) 若仍切不出（行式 transcript：每行一段，如 "WARREN BUFFETT: ..."），按单行切
    if len(chunks) <= 2:
        chunks = [ln for ln in text.split('\n') if ln.strip()]

    # 4) 合并短段，控制每段在 max_chunk_chars 以内
    merged = []
    current = ""
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if not current:
            current = chunk
        elif len(current) + 2 + len(chunk) <= max_chunk_chars:
            current += "\n\n" + chunk
        else:
            merged.append(current)
            current = chunk
    if current:
        merged.append(current)

    # 5) 安全兜底：单段仍超长（如个别超长段落）按句号硬切
    final = []
    for seg in merged:
        if len(seg) <= max_chunk_chars:
            final.append(seg)
            continue
        sentences = re.split(r'(?<=[.!?。！？])\s+', seg)
        cur = ""
        for s in sentences:
            if not cur:
                cur = s
            elif len(cur) + 1 + len(s) <= max_chunk_chars:
                cur += " " + s
            else:
                final.append(cur)
                cur = s
        if cur:
            final.append(cur)
    return final


def translate_file(input_path: str, output_path: str) -> None:
    """主流程：读取文件 → 分段翻译 → 保存结果"""
    # 读取输入
    with open(input_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # 去掉注释行（如 # CHAPTER: ...），这些不属于要翻译/合成的发言内容
    raw_text = re.sub(r'(?m)^\s*#.*$', '', raw_text)
    raw_text = re.sub(r'\n\n+', '\n', raw_text)  # 清理连续空行

    print(f"📄 输入文件: {input_path} ({len(raw_text)} 字符)")

    # 分段
    chunks = split_transcript(raw_text)
    print(f"✂️  切分为 {len(chunks)} 段")

    # 逐段翻译（维护跨 chunk 术语表）
    all_results = []
    glossary = []  # 跨 chunk 术语对照，保持简称一致性
    for i, chunk in enumerate(chunks):
        print(f"\n{'='*50}")
        print(f"🔄 翻译第 {i+1}/{len(chunks)} 段 ({len(chunk)} 字符)..." + (f" [术语表: {len(glossary)} 条]" if glossary else ""))

        try:
            result = call_llm(SYSTEM_PROMPT, build_user_prompt(chunk, glossary if glossary else None))
            all_results.append({
                "index": i,
                "original_length": len(chunk),
                "translated": result,
            })
            # 从译文提取新术语，追加到术语表
            new_terms = extract_glossary(result)
            for t in new_terms:
                if t not in glossary:
                    glossary.append(t)
            # 打印预览
            preview = result[:200] + "..." if len(result) > 200 else result
            print(f"✅ 完成。预览: {preview}")
        except Exception as e:
            print(f"❌ 第 {i+1} 段翻译失败: {e}")
            all_results.append({
                "index": i,
                "original_length": len(chunk),
                "translated": f"[翻译失败] {chunk[:500]}...",
                "error": str(e),
            })

    # 保存结果
    output_data = {
        "source_file": os.path.basename(input_path),
        "total_chunks": len(chunks),
        "api_provider": API_CONFIG["provider"],
        "api_model": API_CONFIG["model"],
        "results": all_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 同时生成纯文本版本，方便后续 TTS 处理
    txt_path = output_path.replace(".json", ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(r["translated"])
            f.write("\n\n")

    print(f"\n{'='*50}")
    print(f"✅ 翻译完成！")
    print(f"   JSON 输出: {output_path}")
    print(f"   文本输出: {txt_path}")

    # 统计
    total_original = sum(r["original_length"] for r in all_results)
    total_translated = sum(len(r["translated"]) for r in all_results)
    print(f"   原文总字符: {total_original}")
    print(f"   译文总字符: {total_translated}")


def main():
    parser = argparse.ArgumentParser(description="巴菲特股东会问答翻译 + 背景增强")
    parser.add_argument("input", help="输入的英文 transcript 文本文件路径")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径（默认：input_translated.json）")
    parser.add_argument("--api-key", help="LLM API Key（也可通过 LLM_API_KEY 环境变量 / config.json 设置）")
    parser.add_argument("--provider", default=None, choices=list(PROVIDERS.keys()),
                        help="切换 LLM 服务商：deepseek / glm / qwen / openai（也可在 config.json 的 llm.provider 设置）")

    args = parser.parse_args()

    # 合并配置：命令行 > 环境变量 > config.json > 注册表
    global API_CONFIG
    API_CONFIG = build_api_config(args)

    if API_CONFIG["api_key"] in (None, "", "your-api-key-here"):
        print("⚠️  未找到 LLM API Key，请任选一种方式提供：")
        print("   1) config.json 的 llm.api_key 填入")
        print("   2) 环境变量 LLM_API_KEY=xxx")
        print("   3) 命令行 --api-key xxx")
        return

    print(f"🤖 使用模型: {API_CONFIG['label']} / {API_CONFIG['model']}")

    # 输出路径
    if args.output is None:
        input_stem = Path(args.input).stem
        args.output = f"{input_stem}_translated.json"

    translate_file(args.input, args.output)


if __name__ == "__main__":
    main()
