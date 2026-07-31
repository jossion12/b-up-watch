"""LLM 观点卡片提取器。

复用 docs/subtitle_to_rag.py 中的 Schema 与 Prompt 思想，但使用项目已有的
app.llm.client.chat（OpenAI 兼容、异步）作为 LLM 调用层。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from app.llm.client import chat

log = logging.getLogger(__name__)


class ArgumentChunk(BaseModel):
    """单个观点卡片（RAG Chunk）。

    字段使用 str 而非 Literal，避免不同 LLM 输出格式微差不一致导致整段丢失。
    系统 Prompt 中仍会给出推荐枚举值引导模型。
    """

    content: str = Field(..., description="清洗后的观点陈述文本，去除口语噪音，保留核心信息")
    content_type: str = Field(
        ...,
        description="内容类型，请从以下选择最接近的一项：观点/事实/预测/叙事/引用/假设/反驳/过渡/广告/口误/情感/方法论"
    )
    argument_role: str = Field(
        ...,
        description="在论证结构中的角色，请从以下选择最接近的一项：主论点/子论点/论据/结论/反驳/让步/类比/个人经验/方法论-教训/背景铺垫/无"
    )
    core_topic: str = Field(..., description="核心主题，如'股票异动偏离值计算'")
    sub_topics: List[str] = Field(default_factory=list, description="子主题标签")
    stance_type: str = Field(
        ...,
        description="立场/观点类型，请从以下选择最接近的一项：支持/反对/中立/预测/判断/建议/经验/无"
    )
    confidence: str = Field(
        ...,
        description="UP主对该观点的置信度，请从以下选择最接近的一项：强/中/弱/未论证"
    )
    verifiability: str = Field(
        ...,
        description="可验证性，请从以下选择最接近的一项：可验证/待验证/不可验证/主观经验"
    )
    source_type: str = Field(
        ...,
        description="信息来源，请从以下选择最接近的一项：UP主本人/引用他人/未知来源"
    )
    original_arguments: List[str] = Field(
        default_factory=list,
        description="支撑该观点的原始论据列表（从字幕中提取的具体事实/案例）",
    )
    time_position: str = Field(..., description="时间位置，如'00:27-00:55'")
    discard_reason: Optional[str] = Field(
        None, description="如果该段应被丢弃，填写原因；否则为null"
    )


class ExtractionResult(BaseModel):
    """一段字幕的提取结果。"""

    chunks: List[ArgumentChunk] = Field(
        ...,
        description="从该段字幕中提取的所有观点卡片。如果整段都是噪音，可以返回空列表或一个带discard_reason的条目",
    )


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
   - 修正明显口误
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

你必须输出一个合法的 JSON 对象，格式如下：
{
  "chunks": [
    {
      "content": "...",
      "content_type": "观点",
      "argument_role": "主论点",
      "core_topic": "...",
      "sub_topics": ["..."],
      "stance_type": "判断",
      "confidence": "强",
      "verifiability": "可验证",
      "source_type": "UP主本人",
      "original_arguments": ["..."],
      "time_position": "00:00 -> 00:10",
      "discard_reason": null
    }
  ]
}
"""


async def extract_chunks(
    segment_text: str,
    time_position: str,
    video_title: str,
    up_name: str,
) -> List[ArgumentChunk]:
    """对单段字幕文本进行观点提取。"""
    user_prompt = f"""视频标题：{video_title or "未知"}
UP主：{up_name or "未知"}
时间段：{time_position}
字幕文本：
{segment_text}

请按系统指令分析以上字幕，输出结构化观点卡片。"""

    try:
        parsed, _ = await chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        result = ExtractionResult.model_validate(parsed)
        valid_chunks: List[ArgumentChunk] = []
        for c in result.chunks:
            if c.discard_reason:
                continue
            c.time_position = time_position
            valid_chunks.append(c)
        return valid_chunks
    except Exception as e:
        log.warning("LLM 提取失败 (%s): %s", time_position, e)
        # 降级：返回一个原始文本的叙事 chunk
        return [
            ArgumentChunk(
                content=segment_text,
                content_type="叙事",
                argument_role="无",
                core_topic="未分类",
                stance_type="无",
                confidence="弱",
                verifiability="不可验证",
                source_type="UP主本人",
                time_position=time_position,
            )
        ]
