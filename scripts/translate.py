"""
巴菲特股东会问答 — 翻译 + 背景增强脚本
使用 DeepSeek API 进行翻译，可替换为 OpenAI / 本地模型

使用方法：
    python translate.py input.txt --output output.json

输入：英文 transcript 文本文件
输出：带翻译和背景补充的 JSON 文件
"""

import argparse
import json
import os
import re
import requests
from pathlib import Path

# ============ 配置 ============
# 支持 DeepSeek（推荐，便宜）或 OpenAI 兼容 API
API_CONFIG = {
    "provider": os.environ.get("LLM_PROVIDER", "deepseek"),  # deepseek / openai
    "api_key": os.environ.get("LLM_API_KEY", "your-api-key-here"),
    "api_url": os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions"),
    "model": os.environ.get("LLM_MODEL", "deepseek-chat"),
}


SYSTEM_PROMPT = """你是一位精通巴菲特投资哲学和伯克希尔·哈撒韦历史的翻译专家。

## 任务
将伯克希尔·哈撒韦股东大会的英文问答翻译成地道的中文，并适当补充背景信息。

## 翻译要求
1. **口语化**：翻译要像自然的中文对话，不要翻译腔。保留巴菲特的幽默感和智慧。
2. **准确性**：金融术语、公司名称、数据必须准确。公司名首次出现时保留英文原名。
3. **人物区分**：明确标注是谁在说话（巴菲特/芒格/提问者）。

## 背景补充规则
在以下情况，用【📌 背景】标记插入背景信息（每段问答最多 1-2 处）：
- 提到某家公司的投资时 → 补充当时伯克希尔的持仓情况
- 涉及宏观经济判断时 → 补充当时的利率/通胀/市场环境
- 巴菲特的经典比喻或反复出现的主题 → 补充他过往的相关论述
- 事件有重要后续发展 → 简要补充（如"注：此后XXX"）

## 输出格式
```
【提问人】姓名（来自XXX机构）
【问题】中文翻译
【巴菲特回答】中文翻译
【📌 背景】背景补充内容（如有）
---
```

注意：
- 不要过度补充，保持问答的流畅节奏
- 背景信息要简洁，不超过 3 句话
- 如果不确定某个背景信息，宁可省略不要编造
"""


def build_user_prompt(text: str) -> str:
    """构建用户消息"""
    return f"请翻译以下伯克希尔·哈撒韦股东大会问答：\n\n{text}"


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

    print(f"📡 正在调用 {API_CONFIG['provider']} API ({API_CONFIG['model']})...")

    response = requests.post(API_CONFIG["api_url"], headers=headers, json=payload, timeout=120)
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
    将长 transcript 按问答对切分，确保每段不超过 max_chunk_chars
    简单策略：按空行切分，合并短段
    """
    # 先尝试按 "Question:" 或 "Q:" 切分
    qa_pattern = r'(?=(?:Question|Q|QUESTION)(?:\s*\d+)?[:\n])'
    chunks = re.split(qa_pattern, text)

    # 如果切出来太少（说明不是标准格式），按空行切
    if len(chunks) <= 2:
        chunks = re.split(r'\n\n+', text)

    # 合并过短的段，控制每段在 max_chunk_chars 以内
    merged = []
    current = ""
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(current) + len(chunk) < max_chunk_chars:
            current += "\n\n" + chunk if current else chunk
        else:
            if current:
                merged.append(current)
            current = chunk
    if current:
        merged.append(current)

    return merged


def translate_file(input_path: str, output_path: str) -> None:
    """主流程：读取文件 → 分段翻译 → 保存结果"""
    # 读取输入
    with open(input_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    print(f"📄 输入文件: {input_path} ({len(raw_text)} 字符)")

    # 分段
    chunks = split_transcript(raw_text)
    print(f"✂️  切分为 {len(chunks)} 段")

    # 逐段翻译
    all_results = []
    for i, chunk in enumerate(chunks):
        print(f"\n{'='*50}")
        print(f"🔄 翻译第 {i+1}/{len(chunks)} 段 ({len(chunk)} 字符)...")

        try:
            result = call_llm(SYSTEM_PROMPT, build_user_prompt(chunk))
            all_results.append({
                "index": i,
                "original_length": len(chunk),
                "translated": result,
            })
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
    parser.add_argument("--api-key", help="LLM API Key（也可通过 LLM_API_KEY 环境变量设置）")

    args = parser.parse_args()

    # API Key 处理
    if args.api_key:
        API_CONFIG["api_key"] = args.api_key

    if API_CONFIG["api_key"] == "your-api-key-here":
        print("⚠️  请设置 LLM_API_KEY 环境变量或通过 --api-key 参数提供 API Key")
        print("   DeepSeek 申请: https://platform.deepseek.com/")
        print("   示例: export LLM_API_KEY=sk-xxxxx")
        return

    # 输出路径
    if args.output is None:
        input_stem = Path(args.input).stem
        args.output = f"{input_stem}_translated.json"

    translate_file(args.input, args.output)


if __name__ == "__main__":
    main()
