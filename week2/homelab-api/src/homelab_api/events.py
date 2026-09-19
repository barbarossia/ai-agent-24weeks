"""流式端点基础：Server-Sent Events（SSE）与 WebSocket。

为什么 Agent 场景需要它们？
- **SSE**：服务器 → 客户端的单向流。LLM 逐 token 输出、工具执行进度就是典型用例；
  它基于普通 HTTP，客户端用 ``EventSource`` 即可，比 WebSocket 更简单。
- **WebSocket**：双向、长连接。适合需要客户端持续发指令的交互式 Agent 会话。

两者都依赖"单线程事件循环能同时挂起很多连接"这一 async 特性。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from .deps import InventoryDep, ProbeDep
from .schemas import CheckResultOut
from .service_async import check_host_async

__all__ = ["router"]

router = APIRouter(tags=["stream"])


@router.get(
    "/events/checks",
    summary="SSE：逐条推送主机检查结果",
    description="``text/event-stream``；每检查完一台主机推送一个 ``event: check``，最后 ``event: done``。",
)
async def stream_checks(
    inventory: InventoryDep,
    probe: ProbeDep,
) -> StreamingResponse:
    async def event_source():
        # 用异步生成器逐个 yield：每台主机一就绪就推给客户端，
        # 而不是等全部检查完再一次性返回（那是普通 JSON 接口的行为）。
        for host in inventory.hosts:
            result = await check_host_async(host, probe=probe)
            payload = CheckResultOut.from_domain(result).model_dump(mode="json")
            yield f"event: check\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.websocket("/ws/checks")
async def ws_checks(
    websocket: WebSocket,
    inventory: InventoryDep,
    probe: ProbeDep,
) -> None:
    """接收主机名文本 → 返回该主机的检查结果 JSON；未知主机返回错误 JSON。

    约定：
    - 客户端发送：``"openwrt-01"``
    - 服务端返回：``{"host": {...}, "status": "...", ...}``
    - 未知主机：``{"error": {"code": "host_not_found", ...}}``（连接保持）
    """
    await websocket.accept()
    try:
        while True:
            name = await websocket.receive_text()
            host = inventory.find(name)
            if host is None:
                await websocket.send_json(
                    {
                        "error": {
                            "code": "host_not_found",
                            "message": f"host not found: {name!r}",
                            "hostname": name,
                        }
                    }
                )
                continue
            result = await check_host_async(host, probe=probe)
            await websocket.send_json(
                CheckResultOut.from_domain(result).model_dump(mode="json")
            )
    except WebSocketDisconnect:
        # 客户端正常关闭；无需报错。
        return
