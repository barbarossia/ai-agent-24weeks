import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from homelab_knowledge_agent import cli, generation, homelab, rag
from homelab_knowledge_agent.errors import IntegrationBlocked


def test_rag_read_only_contract(monkeypatch):
    monkeypatch.setenv("W11_DATABASE_URL", "test-only-placeholder")
    monkeypatch.setenv("W11_PROVIDER", "mock")
    monkeypatch.setenv("W11_DIMENSION", "128")
    store = MagicMock()
    store.search.return_value = [{"content": "fixture"}]
    connect = Mock(return_value=store)
    monkeypatch.setattr(rag.PgStore, "connect", connect)
    assert rag.Week11Retrieval(2, "fixture.md", ["ops"]).retrieve("health") == [{"content": "fixture"}]
    assert store.conn.execute.call_args_list[0].args == ("SET TRANSACTION READ ONLY",)
    args = store.search.call_args.args
    assert args[1].dimension == 128
    assert args[2:] == (2, "fixture.md", ["ops"])
    store.initialize.assert_not_called()
    store.index.assert_not_called()
    store.delete.assert_not_called()
    store.close.assert_called_once()


def test_rag_absent_config_no_discovery(monkeypatch):
    for key in ("W11_DATABASE_URL", "PGSERVICE", "PGHOST", "PGDATABASE", "PGUSER"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(IntegrationBlocked, match="configuration is absent"):
        rag.Week11Retrieval().retrieve("question")


def test_rag_error_redacted_and_closed(monkeypatch):
    monkeypatch.setenv("W11_DATABASE_URL", "placeholder")
    monkeypatch.setenv("W11_PROVIDER", "mock")
    store = MagicMock()
    store.search.side_effect = RuntimeError("secret connection detail")
    monkeypatch.setattr(rag.PgStore, "connect", Mock(return_value=store))
    with pytest.raises(IntegrationBlocked) as error:
        rag.Week11Retrieval().retrieve("q")
    assert "secret" not in str(error.value)
    store.close.assert_called_once()


def test_mcp_environment_forces_mock(monkeypatch):
    monkeypatch.setenv("HOMELAB_MODE", "openwrt")
    monkeypatch.setenv("OPENWRT_CONFIG_JSON", "private")
    monkeypatch.setenv("OPENWRT_CONFIG_FILE", "private-file")
    params = homelab.server_parameters()
    assert params.env["HOMELAB_MODE"] == "mock"
    assert not any(k.startswith("OPENWRT_") for k in params.env)
    assert params.args == ["-m", "homelab_mcp_server.server"]


def result(value):
    return SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text=json.dumps(value))])


def test_mcp_session_calls_only_allowlisted_read_tools(monkeypatch):
    session = Mock()
    session.initialize = AsyncMock()
    session.call_tool = AsyncMock(side_effect=[result({"adapter_mode": "mock", "read_only": True}), result([{"status": "healthy"}])])
    @asynccontextmanager
    async def fake_stdio(parameters):
        assert parameters.env["HOMELAB_MODE"] == "mock"
        yield object(), object()
    @asynccontextmanager
    async def fake_session(*args):
        yield session
    monkeypatch.setattr(homelab, "stdio_client", fake_stdio)
    monkeypatch.setattr(homelab, "ClientSession", fake_session)
    live = asyncio.run(homelab.MockHomeLab().collect())
    assert live["adapter"] == "MockAdapter"
    assert [c.args[0] for c in session.call_tool.call_args_list] == ["ping", "get_health_status"]


class FakeAppServer:
    def __init__(self, account="chatgpt", final_status="completed"):
        self.calls = []
        self.account = account
        self.final_status = final_status
        self.events = iter([
            {"method": "item/completed", "params": {"threadId": "thread", "turnId": "turn",
                "item": {"type": "agentMessage", "phase": "commentary", "text": "not final"}}},
            {"method": "item/completed", "params": {"threadId": "thread", "turnId": "turn",
                "item": {"type": "agentMessage", "phase": "final_answer", "text": "combined answer"}}},
            {"method": "turn/completed", "params": {"threadId": "thread", "turn": {"id": "turn", "status": final_status}}},
        ])

    async def request(self, method, params):
        self.calls.append((method, params))
        return {"account/read": {"account": {"type": self.account}},
                "config/read": {"config": {"mcp_servers": {}}},
                "thread/start": {"thread": {"id": "thread"}},
                "turn/start": {"turn": {"id": "turn"}}}[method]

    async def event(self):
        return next(self.events)


def connect_fake(client):
    @asynccontextmanager
    async def connect():
        yield client
    return connect


def test_supported_generation_flow_fresh_ephemeral_thread():
    client = FakeAppServer()
    model = generation.CodexGeneration("chosen-model", connect_fake(client))
    assert asyncio.run(model.generate("both evidence sources")) == "combined answer"
    calls = dict(client.calls)
    assert calls["thread/start"]["ephemeral"] is True
    assert calls["thread/start"]["sandbox"] == "read-only"
    assert calls["thread/start"]["modelProvider"] == "openai"
    assert calls["turn/start"]["input"][0]["text"] == "both evidence sources"
    assert "thread/resume" not in calls


@pytest.mark.parametrize("account", [None, "apiKey", "chatgptAuthTokens", "amazonBedrock"])
def test_wrong_auth_stops_before_model_request(account):
    client = FakeAppServer(account)
    model = generation.CodexGeneration("chosen-model", connect_fake(client))
    with pytest.raises(IntegrationBlocked, match="ChatGPT-managed"):
        asyncio.run(model.generate("question"))
    assert [method for method, _ in client.calls] == ["account/read"]


def test_failed_turn_not_reported_as_success():
    client = FakeAppServer(final_status="failed")
    with pytest.raises(IntegrationBlocked, match="turn failed"):
        asyncio.run(generation.CodexGeneration("model", connect_fake(client)).generate("q"))


def test_jsonl_interleaved_notifications_and_initialization():
    async def run():
        reader = asyncio.StreamReader()
        for message in [{"method": "thread/started", "params": {}}, {"id": 1, "result": {"ok": True}}]:
            reader.feed_data((json.dumps(message) + "\n").encode())
        reader.feed_eof()
        writer = Mock(drain=AsyncMock())
        client = generation.JsonlClient(SimpleNamespace(stdout=reader, stdin=writer))
        assert await client.request("initialize", {}) == {"ok": True}
        assert (await client.event())["method"] == "thread/started"
        assert json.loads(writer.write.call_args.args[0])["method"] == "initialize"
    asyncio.run(run())


def test_server_environment_excludes_secrets(monkeypatch):
    for name in ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN", "W11_DATABASE_URL", "OPENWRT_CONFIG_JSON"):
        monkeypatch.setenv(name, "do-not-forward")
    assert not any(value == "do-not-forward" for value in generation.server_environment().values())


def test_cli_fake_answer_and_help(monkeypatch, capsys):
    fake = Mock(answer=AsyncMock(return_value="combined fixture answer"))
    monkeypatch.setattr(cli, "build_agent", Mock(return_value=fake))
    assert cli.main(["ask", "question", "--model", "example"]) == 0
    assert "combined fixture answer" in capsys.readouterr().out
    with pytest.raises(SystemExit) as done:
        cli.main(["--help"])
    assert done.value.code == 0


def test_cli_blocker_exit_and_no_raw_errors(monkeypatch, capsys):
    fake = Mock(answer=AsyncMock(side_effect=IntegrationBlocked("Database configuration absent")))
    monkeypatch.setattr(cli, "build_agent", Mock(return_value=fake))
    assert cli.main(["ask", "question", "--model", "example"]) == 2
    assert "Database configuration absent" in capsys.readouterr().err
    fake.answer.side_effect = RuntimeError("secret raw exception")
    assert cli.main(["ask", "question", "--model", "example"]) == 1
    assert "secret" not in capsys.readouterr().err
