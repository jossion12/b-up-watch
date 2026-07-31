#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量字幕 → RAG观点卡片
扫描目录下所有 .srt/.vtt，自动提取并合并为一个JSON

用法：
    python batch_process.py --dir ./subtitles --output all_chunks.json --model kimi-latest
"""

import os
import json
import argparse
from subtitle_to_rag import SubtitleToRAG, LLMExtractor


def batch_process(
    input_dir: str,
    output_path: str,
    api_key: str,
    base_url: str,
    model: str,
    pause_threshold: float = 2.5
):
    extractor = LLMExtractor(api_key=api_key, base_url=base_url, model=model)
    pipeline = SubtitleToRAG(extractor)

    all_results = []
    files = [f for f in os.listdir(input_dir) if f.lower().endswith(('.srt', '.vtt'))]
    files.sort()

    for fname in files:
        fpath = os.path.join(input_dir, fname)
        # 从文件名推断标题（可自定义映射）
        title = os.path.splitext(fname)[0]
        print(f"\n{'='*50}")
        print(f"处理: {fname}")
        print(f"{'='*50}")
        results = pipeline.process(
            subtitle_path=fpath,
            video_title=title,
            up_name="",  # 可从文件名或元数据读取
            pause_threshold=pause_threshold
        )
        all_results.extend(results)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"批量处理完成: {len(files)} 个文件, {len(all_results)} 个观点卡片")
    print(f"输出: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="批量字幕 → RAG观点卡片")
    parser.add_argument("--dir", "-d", required=True, help="字幕文件目录")
    parser.add_argument("--output", "-o", default="all_chunks.json", help="合并输出JSON")
    parser.add_argument("--model", "-m", default="kimi-latest", help="LLM模型")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""), help="API Key")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.moonshot.cn/v1"))
    parser.add_argument("--pause", type=float, default=2.5)
    args = parser.parse_args()

    if not args.api_key:
        print("错误: 请设置 OPENAI_API_KEY")
        return

    batch_process(args.dir, args.output, args.api_key, args.base_url, args.model, args.pause)


if __name__ == "__main__":
    main()
