"""模板渲染 / 变量校验 / 输出契约校验 单元测试。"""

import pytest

from app.llm import prompts


def _ok_prompt() -> str:
    return (
        "标题: {{title}}\n"
        "UP主: {{uploader}}\n"
        "时长: {{duration}}\n"
        "标签: {{tags}}\n"
        "字幕: {{subtitle}}\n"
    )


# ---------- validate_template_variables ----------

def test_validate_passes_for_full_template():
    prompts.validate_template_variables(_ok_prompt())  # 不应抛


def test_validate_fails_missing_subtitle():
    p = "{{title}} {{uploader}} {{duration}} {{tags}}"
    with pytest.raises(prompts.TemplateError, match="subtitle"):
        prompts.validate_template_variables(p)


def test_validate_fails_missing_other_var():
    p = "{{title}} {{subtitle}} {{uploader}} {{duration}}"  # 缺 tags
    with pytest.raises(prompts.TemplateError, match="tags"):
        prompts.validate_template_variables(p)


# ---------- render_template ----------

def test_render_success():
    rendered = prompts.render_template(_ok_prompt(), {
        "title": "t1",
        "uploader": "u1",
        "duration": "1:23",
        "tags": "a,b",
        "subtitle": "hello",
    })
    assert "t1" in rendered
    assert "u1" in rendered
    assert "1:23" in rendered
    assert "a,b" in rendered
    assert "hello" in rendered


def test_render_fails_missing_variable():
    with pytest.raises(prompts.TemplateError) as excinfo:
        prompts.render_template(_ok_prompt(), {
            "title": "t1", "uploader": "u1", "duration": "1:23",  # 缺 tags, subtitle
        })
    assert "tags" in str(excinfo.value) or "subtitle" in str(excinfo.value)


# ---------- validate_summary_output ----------

def _valid_obj():
    return {
        "brief": "测试摘要",
        "points": ["p1", "p2", "p3"],
        "stance": {"label": "积极", "sentiment": "positive", "detail": "支持"},
        "topics": ["t1", "t2", "t3"],
        "quote": "金句",
    }


def test_validate_output_success():
    out = prompts.validate_summary_output(_valid_obj())
    assert out["brief"] == "测试摘要"


def test_validate_output_missing_brief():
    obj = _valid_obj()
    del obj["brief"]
    with pytest.raises(prompts.TemplateError, match="brief"):
        prompts.validate_summary_output(obj)


def test_validate_output_points_out_of_range():
    obj = _valid_obj()
    obj["points"] = ["only"]
    with pytest.raises(prompts.TemplateError, match="points"):
        prompts.validate_summary_output(obj)


def test_validate_output_stance_bad_sentiment():
    obj = _valid_obj()
    obj["stance"]["sentiment"] = "angry"
    with pytest.raises(prompts.TemplateError, match="sentiment"):
        prompts.validate_summary_output(obj)


def test_validate_output_topics_empty():
    obj = _valid_obj()
    obj["topics"] = []
    with pytest.raises(prompts.TemplateError, match="topics"):
        prompts.validate_summary_output(obj)


def test_validate_output_quote_missing():
    obj = _valid_obj()
    del obj["quote"]
    with pytest.raises(prompts.TemplateError, match="quote"):
        prompts.validate_summary_output(obj)
