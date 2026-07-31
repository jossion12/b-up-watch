#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[已弃用] 视频字幕 → RAG观点卡片 自动化提取器

该独立脚本为早期原型，其功能已合并进后端 RAG 模块：
- 解析/切分：backend/app/rag/parser.py
- 观点提取：backend/app/rag/extractor.py
- 向量库存储：backend/app/rag/milvus_store.py
- 服务编排：backend/app/rag/service.py
- REST API：backend/app/api/rag.py

后续请优先使用后端服务与 API；该脚本不再维护，并可能在将来删除。

支持 .srt / .vtt 格式，输出结构化JSON观点卡片

依赖：
    pip install pydantic openai

用法：
    export OPENAI_API_KEY="your-key"
    export OPENAI_BASE_URL="https://api.moonshot.cn/v1"
    python subtitle_to_rag.py --input video.srt --output chunks.json --model kimi-latest --title "视频标题" --up "UP主名"
"""

import re
import json
import os
import argparse
from typing import List, Optional, Literal
from dataclasses import dataclass
from pydantic import BaseModel, Field


# ============================================================
# 1. 字幕解析器
# ============================================================

@dataclass
class SubtitleEntry:
    """单条字幕条目"""
    index: int
    start_time: str      # 原始时间字符串，如 "00:00:01,000"
    end_time: str
    start_seconds: float # 转换为秒，便于计算
    end_seconds: float
    text: str


class SubtitleParser:
    """解析 SRT / VTT 字幕文件"""

    @staticmethod
    def _time_to_seconds(time_str: str) -> float:
        """将 00:00:01,000 或 00:00:01.000 转为秒"""
        time_str = time_str.replace(',', '.').strip()
        parts = time_str.split(':')
        h, m = int(parts[0]), int(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s

    @classmethod
    def parse_srt(cls, content: str) -> List[SubtitleEntry]:
        """解析SRT格式"""
        entries = []
        # 按空行分割块 (兼容不同换行符)
        blocks = re.split(r'\n[ \t]*\n', content.strip())
        for block in blocks:
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            if len(lines) < 3:
                continue
            # 第一行是序号
            try:
                idx = int(lines[0])
            except ValueError:
                continue
            # 第二行是时间
            time_match = re.match(
                r'(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})',
                lines[1]
            )
            if not time_match:
                continue
            start, end = time_match.group(1), time_match.group(2)
            # 剩余是文本
            text = ' '.join(lines[2:])
            entries.append(SubtitleEntry(
                index=idx,
                start_time=start,
                end_time=end,
                start_seconds=cls._time_to_seconds(start),
                end_seconds=cls._time_to_seconds(end),
                text=text
            ))
        return entries

    @classmethod
    def parse_vtt(cls, content: str) -> List[SubtitleEntry]:
        """解析VTT格式（简化版）"""
        entries = []
        lines = content.strip().split('\n')
        # 去掉WEBVTT头
        if lines[0].strip().upper().startswith('WEBVTT'):
            lines = lines[1:]
        # VTT块之间也是空行分隔
        buffer = []
        idx = 0
        for line in lines:
            line = line.strip()
            if not line and buffer:
                # 处理一个块
                time_match = re.match(
                    r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})',
                    buffer[0]
                )
                if time_match:
                    idx += 1
                    start, end = time_match.group(1), time_match.group(2)
                    text = ' '.join(buffer[1:])
                    entries.append(SubtitleEntry(
                        index=idx,
                        start_time=start,
                        end_time=end,
                        start_seconds=cls._time_to_seconds(start),
                        end_seconds=cls._time_to_seconds(end),
                        text=text
                    ))
                buffer = []
            else:
                buffer.append(line)
        # 处理最后一个块
        if buffer:
            time_match = re.match(
                r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})',
                buffer[0]
            )
            if time_match:
                idx += 1
                start, end = time_match.group(1), time_match.group(2)
                text = ' '.join(buffer[1:])
                entries.append(SubtitleEntry(
                    index=idx,
                    start_time=start,
                    end_time=end,
                    start_seconds=cls._time_to_seconds(start),
                    end_seconds=cls._time_to_seconds(end),
                    text=text
                ))
        return entries

    @classmethod
    def parse(cls, file_path: str) -> List[SubtitleEntry]:
        """自动识别格式并解析"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if file_path.lower().endswith('.vtt') or 'WEBVTT' in content[:20].upper():
            return cls.parse_vtt(content)
        return cls.parse_srt(content)


# ============================================================
# 2. 文本清洗器
# ============================================================

class TextCleaner:
    """清洗口语化字幕文本"""

    # 高频无意义口语词（可扩展）
    FILLER_WORDS = [
        '呃', '啊', '哎', '哎呀', '哎呦', '嗯', '呢', '吧', '嘛',
        '就是', '然后', '那个', '这个', '那么', '其实', '反正',
        '说实话', '说白了', '说白了啊', '大家知道吧', '你们知道吗',
        '我跟你说', '我跟你们讲', '我跟大家讲',
    ]

    # 纯情感感叹（通常可丢弃）
    EMOTIONAL_PATTERNS = [
        r'太[牛逼吊强厉害]了[啊]*',
        r'我[靠草操]',
        r'赚[死麻]了',
        r'后悔[啊]*',
        r'真的[是]*[太很]',
        r'[非常特别]的[硬强]',
    ]

    @classmethod
    def clean(cls, entries: List[SubtitleEntry]) -> str:
        """
        将字幕条目合并为连贯段落文本
        策略：
        1. 合并短句（单条字幕通常是一个短句）
        2. 去掉纯重复
        3. 保留时间锚点信息（用于后续溯源）
        """
        texts = []
        prev_text = ""
        for e in entries:
            t = e.text.strip()
            # 跳过纯数字、纯符号
            if not t or re.match(r'^[\d\s\W]+$', t):
                continue
            # 去重：与上一条完全相同的跳过
            if t == prev_text:
                continue
            # 简单去填充词（开头）
            for fw in cls.FILLER_WORDS:
                if t.startswith(fw):
                    t = t[len(fw):].strip()
            # 去掉首尾标点残留
            t = t.strip(' ,.，。')
            if t:
                texts.append(t)
                prev_text = t
        return '。'.join(texts) + '。'

    @classmethod
    def segment_by_pause(cls, entries: List[SubtitleEntry], pause_threshold: float = 2.0) -> List[dict]:
        """
        按时间间隔将字幕切分为「话题段」
        如果两条字幕之间间隔超过 pause_threshold 秒，认为是话题切换
        返回: [{start_time, end_time, text, time_position, entries}, ...]
        """
        segments = []
        current = []
        for i, e in enumerate(entries):
            if not current:
                current.append(e)
            else:
                gap = e.start_seconds - current[-1].end_seconds
                if gap > pause_threshold:
                    # 结束当前段
                    seg_text = ' '.join([x.text for x in current])
                    segments.append({
                        'start_time': current[0].start_time,
                        'end_time': current[-1].end_time,
                        'start_seconds': current[0].start_seconds,
                        'end_seconds': current[-1].end_seconds,
                        'text': seg_text,
                        'time_position': f"{current[0].start_time} -> {current[-1].end_time}",
                        'entries': current
                    })
                    current = [e]
                else:
                    current.append(e)
        # 最后一段
        if current:
            seg_text = ' '.join([x.text for x in current])
            segments.append({
                'start_time': current[0].start_time,
                'end_time': current[-1].end_time,
                'start_seconds': current[0].start_seconds,
                'end_seconds': current[-1].end_seconds,
                'text': seg_text,
                'time_position': f"{current[0].start_time} -> {current[-1].end_time}",
                'entries': current
            })
        return segments


# ============================================================
# 3. LLM 结构化提取（Pydantic Schema）
# ============================================================

class ArgumentChunk(BaseModel):
    """单个观点卡片（RAG Chunk）"""
    content: str = Field(..., description="清洗后的观点陈述文本，去除口语噪音，保留核心信息")
    content_type: Literal[
        "观点", "事实", "预测", "叙事", "引用", "假设",
        "反驳", "过渡", "广告", "口误", "情感", "方法论"
    ] = Field(..., description="内容类型")
    argument_role: Literal[
        "主论点", "子论点", "论据", "结论", "反驳", "让步",
        "类比", "个人经验", "方法论-教训", "背景铺垫", "无"
    ] = Field(..., description="在论证结构中的角色")
    core_topic: str = Field(..., description="核心主题，如'长鑫科技上市走势'")
    sub_topics: List[str] = Field(default_factory=list, description="子主题标签")
    stance_type: Literal["支持", "反对", "中立", "预测", "判断", "建议", "经验", "无"] = Field(
        ..., description="立场/观点类型"
    )
    confidence: Literal["强", "中", "弱", "未论证"] = Field(..., description="UP主对该观点的置信度")
    verifiability: Literal["可验证", "待验证", "不可验证", "主观经验"] = Field(..., description="可验证性")
    source_type: Literal["UP主本人", "引用他人", "未知来源"] = Field(..., description="信息来源")
    original_arguments: List[str] = Field(
        default_factory=list,
        description="支撑该观点的原始论据列表（从字幕中提取的具体事实/案例）"
    )
    time_position: str = Field(..., description="时间位置，如'00:27-00:55'")
    discard_reason: Optional[str] = Field(
        None, description="如果该段应被丢弃，填写原因；否则为null"
    )


class ExtractionResult(BaseModel):
    """一段字幕的提取结果"""
    chunks: List[ArgumentChunk] = Field(
        ...,
        description="从该段字幕中提取的所有观点卡片。如果整段都是噪音，可以返回空列表或一个带discard_reason的条目"
    )


# ============================================================
# 4. LLM 调用封装
# ============================================================

class LLMExtractor:
    """基于LLM的观点提取器"""

    SYSTEM_PROMPT = """你是一位专业的视频内容分析助手。你的任务是将UP主的口语化字幕文本，
转化为结构化的"观点卡片"，用于后续的RAG（检索增强生成）知识库。

## 分析原则

1. **区分内容类型**：
   - 观点：主观判断、立场、建议、预测
   - 事实：可验证的客观陈述（价格、时间、数据）
   - 叙事：个人经历、操作过程
   - 情感：纯感叹、情绪表达（如"太牛逼了""后悔啊"）
   - 方法论：交易策略、操作纪律、经验教训
   - 过渡：衔接语、重复确认
   - 广告/口误：商业推广、明显口误

2. **论证角色识别**：
   - 主论点：视频最核心的判断/预测
   - 子论点：支撑主论点的分支判断
   - 论据：具体的事实、数据、案例
   - 结论：总结性陈述
   - 让步："虽然...但是..."中的让步部分
   - 个人经验：基于个人操作的总结
   - 方法论-教训：从失败中提炼的通用原则

3. **清洗要求**：
   - 去掉口语填充词（"然后""呃""那个"）
   - 合并被截断的短句
   - 修正明显口误（如"长信"→"长鑫"，"摩尔县城"→"摩尔线程"）
   - 保留数字、价格、百分比等关键事实
   - 纯情感感叹若无可提取的观点，标记为discard

4. **置信度判断**：
   - 强：有具体数据/案例支撑，或UP主反复强调
   - 中：有一定逻辑，但证据不够充分
   - 弱：随口一提，缺乏论证
   - 未论证：纯断言

5. **输出要求**：
   - 每个chunk的content必须是完整、通顺的陈述句
   - time_position必须精确到字幕时间段
   - original_arguments列出支撑该观点的具体事实
   - 如果一段内容完全无价值（纯寒暄、纯广告、纯噪音），返回discard_reason
"""

    def __init__(self, api_key: str, base_url: str, model: str):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def extract(self, segment: dict, video_title: str = "", up_name: str = "") -> List[ArgumentChunk]:
        """对单段字幕进行观点提取"""
        user_prompt = f"""视频标题：{video_title or "未知"}
UP主：{up_name or "未知"}
时间段：{segment['time_position']}
字幕文本：
{segment['text']}

请按系统指令分析以上字幕，输出结构化观点卡片。"""

        try:
            completion = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format=ExtractionResult,
                temperature=0.2,
            )
            result = completion.choices[0].message.parsed
            # 过滤掉被标记为丢弃的
            valid_chunks = []
            for c in result.chunks:
                if c.discard_reason:
                    continue
                # 注入通用元数据
                c.time_position = segment['time_position']
                valid_chunks.append(c)
            return valid_chunks
        except Exception as e:
            print(f"[WARN] LLM提取失败 ({segment['time_position']}): {e}")
            # 降级：返回一个原始文本chunk
            return [ArgumentChunk(
                content=segment['text'],
                content_type="叙事",
                argument_role="无",
                core_topic="未分类",
                stance_type="无",
                confidence="弱",
                verifiability="不可验证",
                source_type="UP主本人",
                time_position=segment['time_position']
            )]


# ============================================================
# 5. 主流程
# ============================================================

class SubtitleToRAG:
    """字幕到RAG观点卡片的完整流水线"""

    def __init__(self, extractor: LLMExtractor):
        self.extractor = extractor

    def process(
        self,
        subtitle_path: str,
        video_title: str = "",
        up_name: str = "",
        pause_threshold: float = 2.5,
        output_path: Optional[str] = None
    ) -> List[dict]:
        """
        主入口
        Args:
            subtitle_path: 字幕文件路径 (.srt 或 .vtt)
            video_title: 视频标题（用于metadata）
            up_name: UP主名称
            pause_threshold: 话题切分的时间间隔阈值（秒）
            output_path: 输出JSON路径，默认不保存
        Returns:
            观点卡片列表（可直接写入向量库）
        """
        print(f"[1/4] 解析字幕: {subtitle_path}")
        entries = SubtitleParser.parse(subtitle_path)
        print(f"      共 {len(entries)} 条字幕")

        print(f"[2/4] 按停顿切分话题段 (阈值: {pause_threshold}s)")
        segments = TextCleaner.segment_by_pause(entries, pause_threshold)
        print(f"      切分为 {len(segments)} 个话题段")

        print("[3/4] LLM提取观点卡片...")
        all_chunks = []
        for i, seg in enumerate(segments, 1):
            print(f"      处理第 {i}/{len(segments)} 段 ({seg['time_position']})...", end=" ")
            chunks = self.extractor.extract(seg, video_title, up_name)
            print(f"提取 {len(chunks)} 个卡片")
            all_chunks.extend(chunks)

        print(f"[4/4] 共提取 {len(all_chunks)} 个观点卡片")

        # 转换为标准JSON格式
        results = []
        for idx, c in enumerate(all_chunks, 1):
            results.append({
                "chunk_id": f"{self._slug(video_title)}_{idx:03d}",
                "content": c.content,
                "metadata": {
                    "video_title": video_title,
                    "up_name": up_name,
                    "time_position": c.time_position,
                    "content_type": c.content_type,
                    "argument_role": c.argument_role,
                    "core_topic": c.core_topic,
                    "sub_topics": c.sub_topics,
                    "stance_type": c.stance_type,
                    "confidence": c.confidence,
                    "verifiability": c.verifiability,
                    "source_type": c.source_type,
                    "original_arguments": c.original_arguments
                }
            })

        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"      已保存到: {output_path}")

        return results

    @staticmethod
    def _slug(text: str) -> str:
        """生成ID用的slug"""
        if not text:
            return "unknown"
        return re.sub(r'[^\w]', '_', text)[:30]


# ============================================================
# 6. CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="字幕 → RAG观点卡片")
    parser.add_argument("--input", "-i", required=True, help="输入字幕文件 (.srt/.vtt)")
    parser.add_argument("--output", "-o", default="rag_chunks.json", help="输出JSON路径")
    parser.add_argument("--title", "-t", default="", help="视频标题")
    parser.add_argument("--up", "-u", default="", help="UP主名称")
    parser.add_argument("--model", "-m", default="kimi-latest", help="LLM模型名")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""), help="API Key")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.moonshot.cn/v1"), help="API Base URL")
    parser.add_argument("--pause", type=float, default=2.5, help="话题切分停顿阈值(秒)")
    args = parser.parse_args()

    if not args.api_key:
        print("错误: 请设置 OPENAI_API_KEY 环境变量或通过 --api-key 传入")
        return

    extractor = LLMExtractor(api_key=args.api_key, base_url=args.base_url, model=args.model)
    pipeline = SubtitleToRAG(extractor)

    pipeline.process(
        subtitle_path=args.input,
        video_title=args.title,
        up_name=args.up,
        pause_threshold=args.pause,
        output_path=args.output
    )


if __name__ == "__main__":
    main()
