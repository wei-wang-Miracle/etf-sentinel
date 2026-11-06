"""外部只读数据源的重试与安全错误验证。"""

from datetime import date

import httpx
import pytest

from app import collection


def test_retry_temporary_error(monkeypatch):
    monkeypatch.setenv("CHATBI_TOKEN", "test-secret")
    monkeypatch.setenv("CHATBI_ACCESS_CODE", "test-code")
    monkeypatch.setattr(collection.time, "sleep", lambda _: None)
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise httpx.ConnectError("test-secret")
        return httpx.Response(200, json={"success": True, "data": []})

    monkeypatch.setattr(collection.httpx, "post", post)
    assert collection.fetch_rows("510500", date(2026, 6, 1), date(2026, 6, 2)) == []
    assert len(calls) == 3


def test_auth_error_is_redacted(monkeypatch):
    monkeypatch.setenv("CHATBI_TOKEN", "test-secret")
    monkeypatch.setenv("CHATBI_ACCESS_CODE", "test-code")
    monkeypatch.setattr(
        collection.httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(401, json={"message": "test-secret"}),
    )
    with pytest.raises(ValueError, match="鉴权失败") as exc:
        collection.fetch_rows("510500", date(2026, 6, 1), date(2026, 6, 2))
    assert "test-secret" not in str(exc.value)
