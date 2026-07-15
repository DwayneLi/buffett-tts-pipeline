"""
CNBC 巴菲特股东会 Transcript 爬虫
从 buffett.cnbc.com 爬取历年股东会的整理稿（简介 + Key Chapters + 发言内容）。

用法：
    python crawl_transcripts.py --year 2023              # 爬指定年份
    python crawl_transcripts.py --year 2023,2016,2010    # 爬多个年份
    python crawl_transcripts.py --all                     # 爬全部年份（较慢）
    python crawl_transcripts.py --all --delay 2           # 全部，每次请求间隔 2 秒

输出：samples/brk_{year}_{session}_transcript.txt
"""

import argparse
import html
import json
import os
import re
import time
import urllib.request

BASE = "https://buffett.cnbc.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "samples")


def fetch(url, retries=3):
    """带 UA + 重试的 HTTP 抓取。"""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            if attempt < retries - 1:
                wait = 3 * (attempt + 1)
                print(f"    ⚠️  抓取失败（第{attempt+1}次），{wait}s 后重试: {e}")
                time.sleep(wait)
            else:
                raise


def dec(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s


def fix_mojibake(s):
    try:
        return s.encode('latin-1').decode('utf-8')
    except Exception:
        return s


def clean(s):
    s = re.sub(r'<!--.*?-->', '', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = fix_mojibake(dec(s)) if '\\' in s else fix_mojibake(s)
    return s.strip()


def get_year_links():
    """从 annual-meetings 页获取所有年份链接。"""
    raw = fetch(f"{BASE}/annual-meetings/")
    links = re.findall(r'(https://buffett\.cnbc\.com/(\d{4})-berkshire-hathaway-annual-meeting/)', raw)
    seen = {}
    for url, year in links:
        if year not in seen:
            seen[year] = url
    return dict(sorted(seen.items()))


def get_session_links(year_url):
    """从年份页获取 morning/afternoon session 链接。"""
    raw = fetch(year_url)
    # 从 href 和 JSON 中找 session 视频链接
    # 处理 \u002F 转义
    raw_unescaped = raw.replace('\\u002F', '/')
    links = re.findall(
        r'(https://buffett\.cnbc\.com/video/\d{4}/\d{2}/\d{2}/(?:morning|afternoon)-session[^"\']*\.html)',
        raw_unescaped
    )
    # 去重保序
    seen = []
    for l in links:
        if l not in seen:
            seen.append(l)
    return seen


def extract_transcript(raw):
    """从 session 页 HTML 提取简介、Key Chapters 和发言稿。"""
    # 简介
    intro = ""
    m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', raw)
    if m:
        intro = clean(m.group(1))

    # Key Chapters
    key_chapters = []
    for ol in re.finditer(r'<ol[^>]*>(.*?)</ol>', raw, re.S):
        for li in re.finditer(r'<li[^>]*>(.*?)</li>', ol.group(1), re.S):
            title = clean(li.group(1))
            num_m = re.match(r'^(\d+)\.\s*(.*)', title)
            if num_m:
                key_chapters.append((int(num_m.group(1)), num_m.group(2)))

    # 章节标题 + 发言段落（按顺序）
    chapters = [(m.start(), 'CHAPTER', clean(m.group(1)))
                for m in re.finditer(r'<div class="Chapter-chapterTitle"[^>]*>(.*?)</div>', raw)]
    paragraphs = [(m.start(), 'PARA', clean(m.group(1)))
                  for m in re.finditer(r'<p data-speaker="[^"]*" class="[^"]*">(.*?)</p>', raw)]
    all_items = sorted(chapters + paragraphs, key=lambda x: x[0])

    spk_re = re.compile(r'^([A-Z][A-Z .\'\-]{2,}):\s*(.*)$', re.S)
    out_lines = []
    current_speaker = None
    current_text = []

    def flush():
        nonlocal current_speaker, current_text
        if current_speaker and current_text:
            text = ' '.join(t.strip() for t in current_text if t.strip())
            out_lines.append(f"{current_speaker}: {text}")
        current_speaker = None
        current_text = []

    for _, typ, content in all_items:
        if typ == 'CHAPTER':
            flush()
            out_lines.append(f"# CHAPTER: {content}")
            continue
        m = spk_re.match(content)
        if m:
            flush()
            current_speaker = m.group(1).strip()
            current_text.append(m.group(2).strip())
        else:
            if current_speaker:
                current_text.append(content)
            elif content:
                out_lines.append(f"# NO_SPEAKER: {content}")
    flush()

    # 组装
    header = [f"# INTRO: {intro}", f"# KEY_CHAPTERS: {','.join(str(n) for n, _ in key_chapters)}"]
    if key_chapters:
        header.append("# KEY_CHAPTER_TITLES:")
        for n, t in key_chapters:
            header.append(f"#   {n}. {t}")
    header.append("")

    return "\n".join(header) + "\n".join(out_lines) + "\n", len(out_lines), key_chapters


def crawl_year(year, year_url, delay=1):
    """爬取一年的所有 session transcript（跳过已存在的，容错不中断）。"""
    print(f"\n{'='*60}")
    print(f"📅 {year}: {year_url}")
    print(f"{'='*60}")

    try:
        sessions = get_session_links(year_url)
    except Exception as e:
        print(f"  ❌ 获取 session 链接失败: {e}")
        return []

    if not sessions:
        print(f"  ⚠️  未找到 session 链接")
        return []

    print(f"  找到 {len(sessions)} 个 session:")
    results = []
    for surl in sessions:
        session_name = "morning" if "morning" in surl else "afternoon"
        out_path = os.path.join(SAMPLES_DIR, f"brk_{year}_{session_name}_transcript.txt")

        # 跳过已存在的文件
        if os.path.exists(out_path):
            n = sum(1 for _ in open(out_path, encoding="utf-8"))
            print(f"  → {session_name}: 已存在（{n} 行），跳过")
            results.append((out_path, n, 0))
            continue

        print(f"  → {session_name}: {surl}")
        try:
            raw = fetch(surl)
            time.sleep(delay)
            transcript, n_lines, key_chs = extract_transcript(raw)
            os.makedirs(SAMPLES_DIR, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(transcript)
            print(f"    ✅ {n_lines} 行，{len(key_chs)} 个 Key Chapters → {out_path}")
            results.append((out_path, n_lines, len(key_chs)))
        except Exception as e:
            print(f"    ❌ 抓取失败: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description="CNBC 巴菲特股东会 Transcript 爬虫")
    parser.add_argument("--year", default=None, help="指定年份（逗号分隔，如 2023,2016）")
    parser.add_argument("--all", action="store_true", help="爬取全部年份")
    parser.add_argument("--delay", type=float, default=1.0, help="每次请求间隔秒数（默认 1）")
    args = parser.parse_args()

    print("🔍 获取年份列表...")
    year_links = get_year_links()
    print(f"  共 {len(year_links)} 个年份: {list(year_links.keys())}")

    if args.all:
        targets = year_links
    elif args.year:
        years = [y.strip() for y in args.year.split(",")]
        targets = {y: year_links[y] for y in years if y in year_links}
        if len(targets) < len(years):
            missing = set(years) - set(year_links.keys())
            print(f"  ⚠️  未找到年份: {missing}")
    else:
        print("请指定 --year 或 --all")
        return

    print(f"\n🎯 将爬取 {len(targets)} 个年份")
    total_sessions = 0
    for year, url in targets.items():
        results = crawl_year(year, url, args.delay)
        total_sessions += len(results)
        time.sleep(args.delay)

    print(f"\n{'='*60}")
    print(f"🎉 完成！共爬取 {total_sessions} 个 session")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
