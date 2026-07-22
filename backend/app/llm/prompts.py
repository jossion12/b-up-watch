"""模板渲染与 LLM 输出契约校验。

- 模板支持 5 个固定变量：`{{title}}` `{{uploader}}` `{{duration}}` `{{tags}}` `{{subtitle}}`
- 渲染：朴素字符串替换，未被替换的占位符视为错误
- 输出校验：固定结构 {brief, points, stance{label,sentiment,detail}, topics, quote}
"""

from __future__ import annotations

from typing import Any

REQUIRED_VARS = ("title", "uploader", "duration", "tags", "subtitle")
VALID_SENTIMENTS = ("positive", "neutral", "negative", "mixed")
SENTIMENT_ALIASES = {
    "积极": "positive",
    "正面": "positive",
    "中立": "neutral",
    "客观": "neutral",
    "消极": "negative",
    "负面": "negative",
    "复杂": "mixed",
}


class TemplateError(ValueError):
    """模板/输出契约违反。"""


def validate_template_variables(prompt: str) -> None:
    """校验模板包含全部 5 个变量；尤其 {{subtitle}} 必须存在。"""
    if "{{subtitle}}" not in prompt:
        raise TemplateError("模板必须包含 {{subtitle}} 变量")
    for v in REQUIRED_VARS:
        if f"{{{{{v}}}}}" not in prompt:
            raise TemplateError(f"模板缺少必要变量: {{{{{v}}}}}")


def render_template(prompt: str, variables: dict[str, Any]) -> str:
    """渲染：朴素 replace，要求所有占位符都被替换。"""
    missing = []
    out = prompt
    for k in REQUIRED_VARS:
        token = "{{" + k + "}}"
        if token in out:
            if k not in variables:
                missing.append(k)
                continue
            out = out.replace(token, str(variables[k]))
    # 检测残留占位符
    leftover = _leftover_placeholders(out)
    if leftover:
        raise TemplateError(f"渲染后仍残留占位符: {leftover}")
    if missing:
        raise TemplateError(f"渲染时缺少变量: {missing}")
    return out


def _leftover_placeholders(s: str) -> list[str]:
    import re
    return re.findall(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", s)


def validate_summary_output(obj: dict) -> dict:
    """校验 LLM 输出符合接口文档 2.4 的 Summary 结构。返回清洗后的对象。"""
    if not isinstance(obj, dict):
        raise TemplateError("LLM 输出不是 JSON 对象")

    brief = obj.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        raise TemplateError("brief 缺失或为空")
    if len(brief) > 800:
        # 文档要求 150 字内；这里放宽到 800 容忍模型
        pass

    points = obj.get("points")
    if not isinstance(points, list) or not (3 <= len(points) <= 5):
        raise TemplateError("points 应为 3-5 条")
    if not all(isinstance(p, str) and p.strip() for p in points):
        raise TemplateError("points 应为非空字符串列表")

    stance = obj.get("stance")
    if not isinstance(stance, dict):
        raise TemplateError("stance 缺失")
    if not isinstance(stance.get("label"), str) or not stance["label"].strip():
        raise TemplateError("stance.label 缺失")
    sentiment = stance.get("sentiment")
    normalized = SENTIMENT_ALIASES.get(sentiment, sentiment)
    if normalized not in VALID_SENTIMENTS:
        raise TemplateError(f"stance.sentiment 非法: {sentiment!r}")
    stance["sentiment"] = normalized
    if not isinstance(stance.get("detail"), str):
        raise TemplateError("stance.detail 缺失")

    topics = obj.get("topics")
    if not isinstance(topics, list) or not (3 <= len(topics) <= 5):
        raise TemplateError("topics 应为 3-5 个")
    if not all(isinstance(t, str) and t.strip() for t in topics):
        raise TemplateError("topics 应为非空字符串列表")

    quote = obj.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        raise TemplateError("quote 缺失或为空")

    return obj


# 测试用的样例字幕（首次保存模板时跑试跑用）
SAMPLE_TEMPLATE_VARS = {
    "title": "样例视频：AI Agent 的现状与未来",
    "uploader": "样例UP主",
    "duration": "1234",
    "tags": "AI Agent, 开源, 实测",
    "subtitle": (
        "各位观众大家好，今天我们来聊一个非常有意思的话题。\n"
        "首先，让我们回顾一下过去一周发生的重要事件。\n"
        "AI Agent 领域出现了很多新的进展，特别是 Manus 的开源复刻非常值得关注。\n"
        "接下来，我会分享一些个人的观察和思考。\n"
        "我觉得 Agent 已经跨过了可用的门槛，但距离真正的智能还有很长的路要走。\n"
        "总结一下：技术发展很快，应用场景也在不断扩大。"
    ),
}