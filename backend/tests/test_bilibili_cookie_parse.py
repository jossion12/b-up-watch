"""从 B 站完整 Cookie 字符串中提取 SESSDATA。"""

from __future__ import annotations

import pytest

from app.api.system import _extract_sessdata_from_cookie


@pytest.mark.parametrize(
    "cookie,expected",
    [
        # 标准 DevTools 复制格式
        (
            "SESSDATA=abc123%2Cxyz; bili_jct=foo; DedeUserID=12345",
            "abc123%2Cxyz",
        ),
        # 仅 SESSDATA
        ("SESSDATA=only_one", "only_one"),
        # 大小写不敏感（虽然 B 站实际总是大写）
        ("sessdata=lower_case", "lower_case"),
        # 含前后空白
        ("  SESSDATA=padded  ;  foo=bar  ", "padded"),
        # 空字符串
        ("", None),
        # None
        (None, None),
        # 不含 SESSDATA
        ("foo=bar; baz=qux", None),
        # 值为空（SESSDATA=; 后跟其他）
        ("SESSDATA=; other=val", None),
        # 多个 SESSDATA，取第一个非空
        ("SESSDATA=first; SESSDATA=second", "first"),
        # 包含引号
        ('SESSDATA="quoted_val"; x=y', "quoted_val"),
        # 含 urlencoded 字符
        ("SESSDATA=ab%2Ccd%2Cef%2Cgh", "ab%2Ccd%2Cef%2Cgh"),
    ],
)
def test_extract_sessdata_from_cookie(cookie, expected):
    assert _extract_sessdata_from_cookie(cookie) == expected


def test_extract_handles_realistic_bilibili_cookie():
    """贴近真实 B 站 Cookie：包含 buvid3/buvid4/SESSDATA/bili_jct 等。"""
    real = (
        "buvid3=ABC123DEF456; buvid4=XYZ789; "
        "SESSDATA=11abc%2C22def; "
        "bili_jct=ccc; DedeUserID=12345; sid=abcd"
    )
    assert _extract_sessdata_from_cookie(real) == "11abc%2C22def"


def test_extract_returns_none_for_anonymous_only_cookie():
    """纯匿名追踪 cookie（buvid3/buvid4/_uuid 等，无 SESSDATA）必须返回 None。

    浏览器首次访问 B 站就会被种下这些追踪字段，未登录也有；
    但没有 SESSDATA = 没登录态，必须明确返回 None 让上层告警用户。
    """
    anonymous = (
        "buvid3=D91F2882-F10A-055D-C4DA-E2B56FC5F37E83577infoc; "
        "b_nut=1764460683; "
        "_uuid=5610D3B7A-81046-A11E-78B1-D29BC9C9D17192067infoc; "
        "buvid_fp=8845420ef4a56192324b78c4835f2ecf; "
        "buvid4=61C48DB0-D6EA-4065-B82F-6AFFE310EB5009898-024031001-vKtcjZWf%3D%3D; "
        "CURRENT_QUALITY=0; "
        "rpdid=|(k))k)lm|~Y0J'u~YRRY|~Rl; "
        "theme-tip-show=SHOWED; "
        "_qimei_uuid42=1a1051436331007295d5f4fb2d745c5cfe27a8c66d"
    )
    assert _extract_sessdata_from_cookie(anonymous) is None


def test_extract_handles_cookie_request_header_prefix():
    """DevTools Network → Request Headers → Cookie 行的格式：可能带 'cookie:' 前缀。"""
    with_prefix = (
        "cookie: SESSDATA=11abc%2C22def; buvid3=xxx; bili_jct=ccc"
    )
    assert _extract_sessdata_from_cookie(with_prefix) == "11abc%2C22def"