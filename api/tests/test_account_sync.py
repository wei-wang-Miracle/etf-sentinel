"""账户数据源配置与 HTTP 客户端测试，不访问外网。"""

import json
from datetime import date

import httpx
import pytest

from app.account_sync import AccountConfig, fetch_entrust, fetch_rows, load_config


def config():
    return AccountConfig(
        url="https://example.test/api/sqlapi/api-execute",
        access_code="test-access",
        token="test-token",
        fund_account="12345678",
        start_date=date(2025, 1, 20),
        account_id=1,
    )


def test_load_config_requires_token(monkeypatch):
    monkeypatch.delenv("CHATBI_TOKEN", raising=False)
    with pytest.raises(ValueError, match="CHATBI_TOKEN"):
        load_config()


def test_load_config_reads_local_file(monkeypatch, tmp_path):
    from app import account_sync

    path = tmp_path / "account.json"
    path.write_text('{"fund_account": "0012345678"}')
    monkeypatch.setattr(account_sync, "ACCOUNT_CONFIG_PATH", path)
    monkeypatch.setenv("CHATBI_TOKEN", "shared-token")
    monkeypatch.setenv("ACCOUNT_CHATBI_TOKEN", "ignored-token")
    cfg = load_config()
    assert cfg.token == "shared-token"
    assert cfg.fund_account == "0012345678"
    assert cfg.start_date == date(2025, 1, 20)


@pytest.mark.parametrize("content", [None, "invalid", "[]", '{"fund_account": 123}'])
def test_load_config_rejects_invalid_file(monkeypatch, tmp_path, content):
    from app import account_sync

    path = tmp_path / "account.json"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(account_sync, "ACCOUNT_CONFIG_PATH", path)
    monkeypatch.setenv("CHATBI_TOKEN", "shared-token")
    with pytest.raises(ValueError, match="账户配置"):
        load_config()


def test_fetch_rows_posts_expected_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["api_path"] = request.url.params.get("api_path")
        seen["access_code"] = request.url.params.get("access_code")
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True, "data": [{"STOCK_CODE": "510500"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    rows = fetch_rows(
        "mine/stockreal", {"fundAccount": "12345678"}, client=client, config=config()
    )
    assert rows == [{"STOCK_CODE": "510500"}]
    assert seen == {
        "api_path": "mine/stockreal",
        "access_code": "test-access",
        "auth": "Bearer test-token",
        "body": {"fundAccount": "12345678"},
    }


def test_fetch_rows_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"success": False})

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    with pytest.raises(ValueError, match="鉴权失败"):
        fetch_rows("mine/stockreal", {}, client=client, config=config())


def test_fetch_rows_rejects_bad_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": {"bad": True}})

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    with pytest.raises(ValueError, match="格式"):
        fetch_rows("mine/stockreal", {}, client=client, config=config())


def test_fetch_entrust_sends_date_range():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "data": []})

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    rows = fetch_entrust(
        config(), date(2026, 6, 1), date(2026, 6, 30), client=client
    )
    assert rows == []
    assert seen == [
        {"fundAccount": "12345678", "startDate": "20260601", "endDate": "20260630"}
    ]
