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

# Buffett / Munger speaker name patterns (case-insensitive match)
RE_BUFFETT_SPEAKER = re.compile(r'^(WARREN\s*BUFFETT|BUFFETT)\s*:', re.IGNORECASE)
RE_MUNGER_SPEAKER  = re.compile(r'^(CHARLIE\s*MUNGER|CHARLES\s*MUNGER|MUNGER)\s*:', re.IGNORECASE)


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
    """合并优先级：命令行 > 环境变量 > config.json > 注册表"""
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

## 预处理规则
- 原文中的舞台指示标记（如(Laughter)、(Applause)、(Laughs)、(inaudible)等）已被过滤，无需处理
- `[CHAPTER N] Title` 是章节标题，请翻译为 **【第N章】中文标题**（意译，保留原标题含义）
- `[DIALOGUE N]...[/DIALOGUE N]` 包裹的是同一提问者与巴菲特/芒格的多轮来回对话，**必须翻译为一段连贯的自然对话**，逐句交替呈现提问、插话与回应，不要拆成多个独立的【问题 N】块

## 翻译要求
1. **口语化**：翻译要像自然的中文对话，不要翻译腔。保留巴菲特/芒格的幽默与智慧。
2. **准确性**：金融术语、公司名称、数据必须准确。
3. **全文翻译**：所有英文单词必须翻译为中文，不得在译文中保留任何未翻译的英文词汇。如遇疑似原文拼写错误或畸形单词（如"preemptively"应为"preemptively"），根据上下文语义结合意译或省略，绝不要将拼写错误照搬到译文中。
4. **角色标注**：每段发言用对应标记，只输出实际有发言的角色。
5. **术语简称一致性**：
   - 公司名/人名**首次出现**时，用"中文名即English Name，简称XXX"格式建立对照，如"精密铸件公司即Precision Castparts，简称PCP"。
   - 如果英文原名本身已是简称或缩写形式（如"Blue Chip Stamp"、"GEICO"、"BNSF"），则省略"简称XXX"，直接用"中文名即English Name"即可。
   - **后续出现时**：如原文用全称，译为中文名；如原文用简称，保持简称。不要重复给出英文原名或重复解释。
   - 人名同理：首次"CEO马克·多纳根即Mark Donegan"，后续直接用"马克"。
   - 如果文前已提供术语对照表，严格遵循表中的简称。
   - 全文不使用括号包裹补充说明，改用自然融入正文的方式。
   - **严禁简称冗余**：如"Blue Chip Stamp"本身就是简称，不要输出"Blue Chip Stamp，简称Blue Chip Stamp"。当英文原名与简称相同时，只写"中文名即English Name"。

## 背景补充规则
在以下情况，插入【背景】补充信息（每段问答最多 1 处）：
- 提到某家公司的投资时 → 补充当时伯克希尔的持仓情况、交易内容
- 涉及宏观经济判断时 → 补充当时的利率/通胀/市场环境
- 巴菲特的经典比喻或反复出现的主题 → 补充他过往的相关论述
- 事件有重要后续发展 → 简要补充，包括后续几年间公司的业绩验证
- 背景信息不超过 350 字（不限制句数），不确定则省略，绝不编造
- 背景中避免使用括号进行补充说明，改用自然融入正文的方式
- **禁止使用"注："前缀**，直接陈述事实即可
- **主题去重**：
  - 如果文前提供了"已补充背景的主题"列表，其中已有的主题不再重复补充背景
  - **同一段翻译中**，如果连续多个问题涉及同一主题（如连续多人追问B类股设计），仅第一个问题补充背景，后续同主题追问不再补充
- **跳过非专业问题**：对于个人化寒暄、幽默调侃、体重健康、体育娱乐、开场致辞等非投资专业类问题，不补充背景。判断标准：如果巴菲特+芒格的回答合计较短（预估不足 500 字），且问题本身不含公司名/行业术语/宏观关键词，通常无需背景

## 输出格式

**首先判断原文段落类型**：
- `[DIALOGUE N]...[/DIALOGUE N]` → 对话块，合并翻译为一段交替问答，输出格式：`【问题 N】提问内容... 【巴菲特】回答... 【提问人】追问... 【巴菲特】再答...`
- 如果段落中有 `QUESTION C-Q:` 标记 → 独立问答
- 如果段落中有 `[STATEMENT N]` 标记 → 直接以【巴菲特】或【芒格】开头
- 其他 → 按角色直接翻译

**问答格式**（每个问答之间用 --- 分隔）：
【问题 C-Q】提问人姓名提问：中文翻译
【背景】背景补充内容（如有，最多 1 处，≤350 字，放在问题之后、回答之前）
【巴菲特】巴菲特的中文回答（如该轮他发言）
【芒格】芒格的中文回答（如该轮他发言）
---

注意：
- C-Q 为原文中标注的编号（C=章节号，Q=章节内问题序号），**直接复用，不要修改或重新编号**
- 提问人直接嵌入问题行：如原文为"SOMEONE: text"，译为"某人提问：中文翻译"；如原文未标明提问人姓名，用"股东提问：中文翻译"
- **不要**输出"来自XXX机构"或"来自XXX市"，只保留姓名+提问
- 某轮若只有巴菲特回答，就只输出【巴菲特】；只有芒格就只输出【芒格】；两人都答就各输出一段
- 【背景】放在【问题】之后、【巴菲特】/【芒格】之前，让听众先了解背景再听回答
- 不要过度补充背景，保持问答流畅节奏
- **绝对不要在翻译开头自行添加总结性问题或概述**，只忠实翻译原文内容
- 同一编号的多个 QUESTION 行（如多个 QUESTION 18-3）是同一人与巴菲特/芒格的连续对话，**应将全部同编号片段合并翻译为一段连贯的问答交锋**，不要逐条输出碎片化的问题行
- **【问题 C-Q】是格式占位符示例，永远不要在译文中输出这个字面字符串。**
"""


def build_user_prompt(text: str, glossary: list[str] = None, bg_topics: list[str] = None,
                      current_chapter: int = None) -> str:
    """构建用户消息，可选附带术语对照表 + 当前章节已补充背景主题列表。"""
    prompt = "请翻译以下伯克希尔·哈撒韦股东大会问答：\n\n"
    if glossary:
        prompt += "【已建立的术语对照表】（后续翻译请严格遵循这些简称，不要重复给出英文原名或重复解释）\n"
        prompt += "\n".join(glossary) + "\n\n"
    if bg_topics:
        prompt += "【本章节已补充背景的主题】（仅当问题明确涉及同一具体主题时才跳过背景，全新主题仍应正常补充）\n"
        prompt += "\n".join(f"- {t}" for t in bg_topics) + "\n\n"
    prompt += text
    return prompt


def strip_stage_directions(text: str) -> str:
    """过滤舞台指示标记：(Laughter)、(Applause)、(Laughs)、(inaudible) 等。"""
    text = re.sub(r'\([Ll]aughter[s]?\)', '', text)
    text = re.sub(r'\([Aa]pplause\)', '', text)
    text = re.sub(r'\([Ll]augh[s]?\)', '', text)
    text = re.sub(r'\(inaudible\)', '', text)
    text = re.sub(r'\([Pp]h\b[^)]*\)', '', text)  # (PH) phonetic markers
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def number_questions(text: str) -> str:
    """在原文中预注入问题编号。【问题 C-Q】格式，C=章节号，Q=章节内问题序号。
    通过解析 [CHAPTER] 标记和发言人名称实现，完全避免 LLM 计数幻觉。
    对于没有提问者、只有巴菲特/芒格发言的章节，注入 [STATEMENT] 标记。"""
    lines = text.split('\n')
    output = []
    chapter_num = 1
    q_num = 1
    chapter_has_questions = False  # 当前章节是否出现过提问者
    last_questioner = None          # 上一个提问者（用于判断是否同一人的追问）

    for line in lines:
        # 追踪章节边界
        chap_match = re.match(r'\[CHAPTER\s*(\d+)\]', line)
        if chap_match:
            if not chapter_has_questions and chapter_num >= 1:
                output.append(f"[STATEMENT {chapter_num}]")
            chapter_num = int(chap_match.group(1))
            q_num = 1
            chapter_has_questions = False
            last_questioner = None
            output.append(line)
            continue

        # 匹配发言人行
        spk_match = re.match(r'^([A-Z][A-Z .\'\-]{2,}):\s*(.*)$', line)
        if spk_match:
            speaker = spk_match.group(1).strip().upper()
            rest = spk_match.group(2)

            is_buffett = bool(re.match(r'^(WARREN\s*)?BUFFETT$', speaker))
            is_munger  = bool(re.match(r'^(CHARLIE\s*|CHARLES\s*)?MUNGER$', speaker))

            if not is_buffett and not is_munger:
                # 同一人连续追问（中间仅隔巴菲特/芒格简短回应）→ 复用同一编号
                if speaker == last_questioner:
                    output.append(f"QUESTION {chapter_num}-{q_num}: {speaker}: {rest}")
                else:
                    q_num += 1
                    output.append(f"QUESTION {chapter_num}-{q_num}: {speaker}: {rest}")
                last_questioner = speaker
                chapter_has_questions = True
            else:
                # 巴菲特/芒格发言后不清空 last_questioner，以便检测追问
                output.append(line)
        else:
            output.append(line)

    # 末尾章节也检查
    if not chapter_has_questions:
        output.append(f"[STATEMENT {chapter_num}]")

    return '\n'.join(output)


def extract_glossary(translated_text: str) -> list[str]:
    """从译文中提取已建立的术语对照（中文名即English，简称XXX格式）。"""
    entries = []
    seen = set()
    for m in re.finditer(r'即([A-Za-z][A-Za-z .\-=]+?)(?:，简称([A-Za-z]+))?', translated_text):
        en = m.group(1).strip()
        abbr = m.group(2) or ""
        key = en.lower()
        if key in seen:
            continue
        seen.add(key)
        before = translated_text[max(0, m.start() - 20):m.start()]
        cn_match = re.search(r'([\u4e00-\u9fa5·]{2,8})$', before)
        cn = cn_match.group(1) if cn_match else ""
        cn = re.sub(r'^(于|关于|对于|的|是|了|在|为|对|由|和|与|及|有|被|将|已|还|也|又|都|就|才|只|会|能|可|应|要|想|说|问|答|来|去|到|从|给|让|把|叫|请|或|这|那|其|该|某|名为|叫|称)', '', cn)
        # 简称与原名相同则省略简称
        if abbr and abbr.lower() == en.lower():
            abbr = ""
        if cn:
            entry = f"- {en} → {cn}" + (f"，简称{abbr}" if abbr else "")
        else:
            entry = f"- {en}" + (f"，简称{abbr}" if abbr else "")
        entries.append(entry)
    return entries


def extract_background_topics(translated_text: str) -> list[str]:
    """从译文中提取已补充背景的主题摘要，用于跨 chunk 去重。"""
    topics = []
    for m in re.finditer(r'【背景】(.+?)(?:\n【|$)', translated_text, re.S):
        bg_text = m.group(1).strip()
        summary = bg_text[:60].strip()
        if summary:
            topics.append(summary)
    return topics


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
            break
        except (requests.RequestException, requests.Timeout) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE ** attempt
                print(f"   ⚠️  第 {attempt} 次调用失败（{e}），{wait:.0f}s 后重试...")
                time.sleep(wait)
            else:
                print(f"   ❌ 重试 {MAX_RETRIES} 次仍失败: {e}")

    if response is None:
        raise last_err or RuntimeError("LLM 调用失败")
    response.raise_for_status()

    data = response.json()
    content = data["choices"][0]["message"]["content"]

    usage = data.get("usage", {})
    if usage:
        print(f"   Tokens: 输入 {usage.get('prompt_tokens', '?')} / 输出 {usage.get('completion_tokens', '?')}")

    return content


def wrap_dialogues(text: str) -> str:
    """将同一编号的多次提问+中间回应包裹为对话块，引导 LLM 合并翻译为连贯对话。"""
    lines = text.split('\n')
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        qm = re.match(r'QUESTION\s+(\d+-\d+):', line)
        if qm:
            qid = qm.group(1)
            # 收集该编号后续所有出现的行（含中间巴菲特/芒格回应）
            group = [line]
            j = i + 1
            has_more = False
            while j < len(lines):
                ln = lines[j]
                if re.match(rf'QUESTION\s+{re.escape(qid)}:', ln):
                    has_more = True
                    group.append(ln)
                    j += 1
                elif re.match(r'^(WARREN|CHARLIE|CHARLES|MUNGER|BUFFETT)\s', ln):
                    group.append(ln)
                    j += 1
                elif re.match(r'^\[CHAPTER|QUESTION\s+\d+-\d+:|^\[STATEMENT|^\[CONTINUATION\]', ln):
                    break
                else:
                    group.append(ln)
                    j += 1
            if has_more:
                out.append(f"[DIALOGUE {qid}]")
                out.extend(group)
                out.append(f"[/DIALOGUE {qid}]")
            else:
                out.extend(group)
            i = j
        else:
            out.append(line)
            i += 1
    return '\n'.join(out)


def split_transcript(text: str, max_chunk_chars: int = 4000) -> list[str]:
    """
    将长 transcript 切分，确保每段不超过 max_chunk_chars（PRD F2-02）。
    策略：优先按 QUESTION 标记切 → 按空行切 → 按单行切 → 合并短段。
    """
    # 1) 优先按 QUESTION 或 DIALOGUE 标记切分
    qa_pattern = r'(?=(?:QUESTION\s+\d+-\d+:|\[DIALOGUE\s+\d+-\d+\]))'
    chunks = re.split(qa_pattern, text)

    # 2) 若切不出来，按空行切
    if len(chunks) <= 2:
        chunks = re.split(r'\n\n+', text)

    # 3) 兜底：按行切
    if len(chunks) <= 2:
        chunks = [ln for ln in text.split('\n') if ln.strip()]

    # 4) 合并短段
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

    # 5) 兜底硬切
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
    """主流程：读取 → 预处理 → 编号注入 → 分段 → 翻译 → 保存"""
    with open(input_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    print(f"📄 输入文件: {input_path} ({len(raw_text)} 字符)")

    # Step 1: 过滤舞台指示标记
    raw_text = strip_stage_directions(raw_text)
    print(f"🧹 预处理后: {len(raw_text)} 字符")

    # Step 2: 保留章节标题 + 去掉其他元数据行
    # # CHAPTER: N. Title → [CHAPTER N] Title（供 LLM 翻译标题用）
    raw_text = re.sub(r'(?m)^#\s*CHAPTER:\s*(\d+)\.\s*(.*)', r'[CHAPTER \1] \2', raw_text)
    raw_text = re.sub(r'(?m)^\s*# (?:INTRO|KEY_CHAPTERS|KEY_CHAPTER_TITLES|MEETING|DATE).*$', '', raw_text)
    raw_text = re.sub(r'(?m)^\s*#\s{2,}.*$', '', raw_text)
    raw_text = re.sub(r'\n{3,}', '\n\n', raw_text)

    # Step 3: 预注入问题编号 + 包裹对话块
    raw_text = number_questions(raw_text)
    raw_text = wrap_dialogues(raw_text)
    print(f"🔢 问题编号已注入")

    # Step 4: 分段
    chunks = split_transcript(raw_text)
    # 确保每个 chunk 都有开头标记：不以 QUESTION/STATEMENT/CONTINUATION 开头的补 [CONTINUATION]
    for idx in range(len(chunks)):
        if not re.match(r'(QUESTION\s+\d+-\d+:|\[STATEMENT|\[CONTINUATION\])', chunks[idx].lstrip()):
            chunks[idx] = "[CONTINUATION] " + chunks[idx]
    print(f"✂️  切分为 {len(chunks)} 段")

    # Step 5: 逐段翻译
    all_results = []
    glossary = []
    bg_topics = []
    last_chapter = 0
    for i, chunk in enumerate(chunks):
        # 检测章节切换 → 重置背景去重（不同章节主题不同）
        chap_m = re.search(r'\[CHAPTER\s*(\d+)\]', chunk)
        cur_chapter = int(chap_m.group(1)) if chap_m else last_chapter
        if cur_chapter != last_chapter:
            bg_topics = []
            last_chapter = cur_chapter

        extra_info = []
        if glossary:
            extra_info.append(f"术语表: {len(glossary)} 条")
        if bg_topics:
            extra_info.append(f"本章已补背景: {len(bg_topics)} 个")
        extra_str = f" [{', '.join(extra_info)}]" if extra_info else ""

        print(f"\n{'='*50}")
        print(f"🔄 翻译第 {i+1}/{len(chunks)} 段 (Ch.{cur_chapter}, {len(chunk)} 字符){extra_str}...")

        try:
            result = call_llm(
                SYSTEM_PROMPT,
                build_user_prompt(chunk, glossary if glossary else None, bg_topics if bg_topics else None, cur_chapter)
            )
            all_results.append({
                "index": i,
                "original_length": len(chunk),
                "translated": result,
            })
            new_terms = extract_glossary(result)
            for t in new_terms:
                if t not in glossary:
                    glossary.append(t)
            new_topics = extract_background_topics(result)
            for t in new_topics:
                if t not in bg_topics:
                    bg_topics.append(t)
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

    # 保存
    output_data = {
        "source_file": os.path.basename(input_path),
        "total_chunks": len(chunks),
        "api_provider": API_CONFIG["provider"],
        "api_model": API_CONFIG["model"],
        "results": all_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    txt_path = output_path.replace(".json", ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(r["translated"])
            f.write("\n\n")

    print(f"\n{'='*50}")
    print(f"✅ 翻译完成！")
    print(f"   JSON 输出: {output_path}")
    print(f"   文本输出: {txt_path}")

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

    global API_CONFIG
    API_CONFIG = build_api_config(args)

    if API_CONFIG["api_key"] in (None, "", "your-api-key-here"):
        print("⚠️  未找到 LLM API Key，请任选一种方式提供：")
        print("   1) config.json 的 llm.api_key 填入")
        print("   2) 环境变量 LLM_API_KEY=xxx")
        print("   3) 命令行 --api-key xxx")
        return

    print(f"🤖 使用模型: {API_CONFIG['label']} / {API_CONFIG['model']}")

    if args.output is None:
        input_stem = Path(args.input).stem
        args.output = f"{input_stem}_translated.json"

    translate_file(args.input, args.output)


if __name__ == "__main__":
    main()
