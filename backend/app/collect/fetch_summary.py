"""LLM 总结主流程：检查字幕 → 渲染模板 → 调 LLM → 校验 → 写入 Summary。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.collect import fetch_subtitle
from app.errors import BizError
from app.insights.aggregator import update_insights_for_summary
from app.llm import client as llm_client
from app.websocket import push_summary_completed_sync
from app.llm import prompts as llm_prompts
from app.models import DEFAULT_USER_ID, Subtitle, Summary, SummaryTemplate, SystemConfig, Video

log = logging.getLogger(__name__)


def _get_template(db: Session, template_id: str | None) -> SummaryTemplate:
    if template_id:
        t = db.get(SummaryTemplate, template_id)
        if t is None:
            raise BizError("TEMPLATE_NOT_FOUND", "模板不存在", http_status=404)
        return t
    t = db.query(SummaryTemplate).filter_by(is_default=True).first()
    if t is None:
        raise BizError("TEMPLATE_NOT_FOUND", "未配置默认模板", http_status=500)
    return t


def _format_duration(sec: int) -> str:
    """duration 字段为人可读的字符串，例如 12:34。"""
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_tags(tags: list[str]) -> str:
    return ", ".join(tags) if tags else ""


async def summarize_video(
    db: Session,
    video: Video,
    *,
    template_id: str | None = None,
    model: str | None = None,
) -> Summary:
    """对单个视频生成总结。前提：字幕已就绪。"""
    # AI 总结功能已暂停
    raise BizError("AI_SUMMARY_DISABLED", "AI 总结功能已暂停", http_status=503)

    # if video.user_id != DEFAULT_USER_ID:
    #     raise BizError("VIDEO_NOT_FOUND", "视频不存在", http_status=404)

    # # 字幕检查（缺则抛 SUBTITLE_UNAVAILABLE）
    # sub = db.get(Subtitle, video.id)
    # if sub is None:
    #     raise BizError(
    #         "SUBTITLE_UNAVAILABLE",
    #         "该视频尚无字幕，请先获取字幕",
    #         http_status=422,
    #     )

    # # 状态：new/subtitled → summarizing
    # video.status = "summarizing"
    # db.commit()

    # template = _get_template(db, template_id)
    # subtitle_text = "\n".join((ln.get("text") or "") for ln in (sub.lines or []))
    # variables = {
    #     "title": video.title or "",
    #     "uploader": video.uploader.name if video.uploader else "",
    #     "duration": _format_duration(video.duration_sec),
    #     "tags": _format_tags(video.tags or []),
    #     "subtitle": subtitle_text,
    # }

    # try:
    #     rendered = llm_prompts.render_template(template.prompt, variables)
    # except llm_prompts.TemplateError as e:
    #     raise BizError("TEMPLATE_RENDER_FAILED", str(e), http_status=500) from e

    # messages = [
    #     {
    #         "role": "system",
    #         "content": (
    #             "你是视频内容分析助手。请严格只输出一个合法的 JSON 对象，"
    #             "不要添加任何解释、markdown 代码块（如 ```json）或其他额外文本。\n\n"
    #             "输出必须包含以下字段，且不允许为空：\n"
    #             '- "brief": 字符串，150字内摘要\n'
    #             '- "points": 字符串数组，3-5条要点\n'
    #             '- "stance": 对象，包含:\n'
    #             '  - "label": 字符串，观点标签，不能为空\n'
    #             '  - "sentiment": 字符串，必须是 positive/neutral/negative/mixed 四选一\n'
    #             '  - "detail": 字符串，观点详细阐述\n'
    #             '- "topics": 字符串数组，3-5个话题标签\n'
    #             '- "quote": 字符串，一句代表性引用\n'
    #         ),
    #     },
    #     {"role": "user", "content": rendered},
    # ]

    # try:
    #     parsed, usage = await llm_client.chat(messages, model=model)
    #     obj = llm_prompts.validate_summary_output(parsed)
    # except BizError:
    #     video.status = "failed"
    #     db.commit()
    #     raise
    # except llm_prompts.TemplateError as e:
    #     video.status = "failed"
    #     db.commit()
    #     raise BizError("SUMMARY_BAD_OUTPUT", f"LLM 输出不符合契约: {e}", http_status=502) from e

    # token_usage = {
    #     "prompt": int(usage.get("prompt_tokens") or 0),
    #     "completion": int(usage.get("completion_tokens") or 0),
    # }

    # summary = db.get(Summary, video.id)
    # if summary is None:
    #     summary = Summary(
    #         video_id=video.id,
    #         template_id=template.id,
    #         brief=obj["brief"],
    #         points=list(obj["points"]),
    #         stance={
    #             "label": obj["stance"]["label"],
    #             "sentiment": obj["stance"]["sentiment"],
    #             "detail": obj["stance"]["detail"],
    #         },
    #         topics=list(obj["topics"]),
    #         quote=obj["quote"],
    #         model=model or (db.get(SystemConfig, 1).summary_model if db.get(SystemConfig, 1) else None),
    #         token_usage=token_usage,
    #         created_at=datetime.now(timezone.utc),
    #     )
    #     db.add(summary)
    # else:
    #     summary.template_id = template.id
    #     summary.brief = obj["brief"]
    #     summary.points = list(obj["points"])
    #     summary.stance = {
    #         "label": obj["stance"]["label"],
    #         "sentiment": obj["stance"]["sentiment"],
    #         "detail": obj["stance"]["detail"],
    #     }
    #     summary.topics = list(obj["topics"])
    #     summary.quote = obj["quote"]
    #     summary.model = model or summary.model
    #     summary.token_usage = token_usage
    #     summary.created_at = datetime.now(timezone.utc)

    # video.has_summary = True
    # video.status = "summarized"
    # db.commit()
    # log.info("summarized video %s using template %s", video.bvid, template.id)

    # # 增量更新洞察聚合表
    # update_insights_for_summary(db, video, summary)

    # # WebSocket 推送：总结完成
    # push_summary_completed_sync(video.id, {
    #     "video_id": summary.video_id,
    #     "template_id": summary.template_id,
    #     "brief": summary.brief,
    #     "points": summary.points or [],
    #     "stance": summary.stance or {},
    #     "topics": summary.topics or [],
    #     "quote": summary.quote,
    #     "model": summary.model,
    #     "token_usage": summary.token_usage or {},
    #     "created_at": summary.created_at,
    # })

    # return summary
