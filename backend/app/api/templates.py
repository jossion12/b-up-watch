"""总结模板管理接口：3.4.5 / 3.4.6 / 3.4.7 / 3.4.8。

首次保存 / 更新时，会用一份样例字幕渲染模板并调一次 LLM，
验证输出符合 2.4 Summary 的 JSON 契约（接口文档 3.4.6）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import BizError
from app.llm import client as llm_client
from app.llm import prompts as llm_prompts
from app.models import SummaryTemplate
from app.schemas import SummaryTemplateIn, SummaryTemplateOut

log = logging.getLogger(__name__)

router = APIRouter()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _out(t: SummaryTemplate) -> SummaryTemplateOut:
    return SummaryTemplateOut(
        id=t.id,
        name=t.name,
        is_default=t.is_default,
        prompt=t.prompt,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


async def _trial_run(prompt: str) -> None:
    """用样例变量渲染 → 调 LLM → 校验输出契约；失败抛 BizError 400。"""
    try:
        rendered = llm_prompts.render_template(prompt, llm_prompts.SAMPLE_TEMPLATE_VARS)
    except llm_prompts.TemplateError as e:
        raise BizError("TEMPLATE_INVALID", f"模板渲染失败: {e}", http_status=400) from e

    messages = [
        {"role": "system", "content": "你是视频内容分析助手，严格输出合法 JSON。"},
        {"role": "user", "content": rendered},
    ]
    try:
        parsed, _usage = await llm_client.chat(messages)
        llm_prompts.validate_summary_output(parsed)
    except BizError as e:
        # LLM 不可达 / 配置错误 / 输出坏 JSON / JSON 不合规，都归到 400（用户行为触发）
        if e.code in ("LLM_BAD_OUTPUT", "SUMMARY_BAD_OUTPUT"):
            raise BizError(e.code, e.message, http_status=400, details=e.details) from e
        if e.code in ("LLM_NOT_CONFIGURED", "LLM_MODEL_MISSING"):
            raise BizError(e.code, e.message, http_status=e.http_status) from e
        raise BizError(
            "TEMPLATE_TRIAL_FAILED",
            f"模板试跑失败: {e.message}",
            http_status=400,
            details=e.details,
        ) from e
    except llm_prompts.TemplateError as e:
        raise BizError(
            "SUMMARY_BAD_OUTPUT",
            f"LLM 输出不符合契约: {e}",
            http_status=400,
        ) from e


def _ensure_prompt_valid(prompt: str) -> None:
    """前置校验：变量齐全 + 含 {{subtitle}}。"""
    try:
        llm_prompts.validate_template_variables(prompt)
    except llm_prompts.TemplateError as e:
        raise BizError("TEMPLATE_INVALID", str(e), http_status=400) from e


def _ensure_only_one_default(db: Session, keep_id: Optional[str] = None) -> None:
    """切换默认时：把其他模板 is_default 清掉。"""
    rows = db.query(SummaryTemplate).filter(SummaryTemplate.is_default.is_(True)).all()
    for t in rows:
        if t.id != keep_id:
            t.is_default = False
    db.commit()


# ---------- 3.4.5 获取模板列表 ----------

@router.get("/summary/templates", response_model=dict)
def list_templates(db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(SummaryTemplate)
        .order_by(SummaryTemplate.is_default.desc(), SummaryTemplate.updated_at.desc())
        .all()
    )
    items = [_out(r).model_dump(mode="json") for r in rows]
    return {"items": items}


# ---------- 3.4.6 新建模板 ----------

@router.post(
    "/summary/templates",
    response_model=SummaryTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    payload: SummaryTemplateIn,
    db: Session = Depends(get_db),
) -> SummaryTemplateOut:
    _ensure_prompt_valid(payload.prompt)

    # 试跑：调一次 LLM
    await _trial_run(payload.prompt)

    now = datetime.now(timezone.utc)
    tpl = SummaryTemplate(
        id="tpl_" + _new_id(),
        name=payload.name,
        is_default=payload.is_default,
        prompt=payload.prompt,
        created_at=now,
        updated_at=now,
    )
    db.add(tpl)

    if payload.is_default:
        _ensure_only_one_default(db, keep_id=tpl.id)
        db.refresh(tpl)
    db.commit()
    db.refresh(tpl)
    return _out(tpl)


# ---------- 3.4.7 更新模板 ----------

@router.put("/summary/templates/{template_id}", response_model=SummaryTemplateOut)
async def update_template(
    template_id: str,
    payload: SummaryTemplateIn,
    db: Session = Depends(get_db),
) -> SummaryTemplateOut:
    t = db.get(SummaryTemplate, template_id)
    if t is None:
        raise BizError("TEMPLATE_NOT_FOUND", "模板不存在", http_status=404)

    _ensure_prompt_valid(payload.prompt)
    await _trial_run(payload.prompt)

    t.name = payload.name
    t.prompt = payload.prompt
    # is_default 在切换时需要事务性更新：先保存新值，在 commit 后做去重
    t.is_default = payload.is_default
    t.updated_at = datetime.now(timezone.utc)
    db.commit()

    if payload.is_default:
        _ensure_only_one_default(db, keep_id=t.id)
        db.refresh(t)
    return _out(t)


# ---------- 3.4.8 删除模板 ----------

@router.delete("/summary/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: str, db: Session = Depends(get_db)) -> Response:
    t = db.get(SummaryTemplate, template_id)
    if t is None:
        raise BizError("TEMPLATE_NOT_FOUND", "模板不存在", http_status=404)
    if t.is_default:
        raise BizError("DEFAULT_TEMPLATE_NOT_DELETABLE", "默认模板不可删除", http_status=400)
    db.delete(t)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
