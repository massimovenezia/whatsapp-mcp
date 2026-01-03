import asyncio
import json
import os
import uvicorn
from main import mcp
from mcp import types
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from sse_starlette.sse import EventSourceResponse

# Configure HTTP transport for streamable MCP over JSON-RPC
mcp.settings.host = "0.0.0.0"
mcp.settings.port = int(os.environ.get("PORT", 3333))

init_options = mcp._mcp_server.create_initialization_options()


def _json_error(
    code: int, message: str, request_id: types.RequestId | None
) -> JSONResponse:
    error_id: types.RequestId = (
        request_id if isinstance(request_id, (str, int)) else 0
    )
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": error_id,
            "error": types.ErrorData(code=code, message=message, data=None).model_dump(
                by_alias=True, exclude_none=True
            ),
        },
        media_type="application/json",
    )


async def handle_jsonrpc(request: Request) -> JSONResponse:
    if "application/json" not in request.headers.get("content-type", ""):
        return _json_error(
            types.INVALID_REQUEST, "Content-Type must be application/json", None
        )

    try:
        payload = await request.json()
    except Exception:
        return _json_error(types.PARSE_ERROR, "Could not parse JSON body", None)

    if not isinstance(payload, dict):
        return _json_error(
            types.INVALID_REQUEST, "Request body must be a JSON object", None
        )

    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    if payload.get("jsonrpc") != "2.0" or request_id is None or not isinstance(
        method, str
    ):
        return _json_error(types.INVALID_REQUEST, "Invalid JSON-RPC request", request_id)

    # Dispatch supported MCP methods
    if method == "initialize":
        result = {
            "protocolVersion": types.LATEST_PROTOCOL_VERSION,
            "capabilities": init_options.capabilities.model_dump(
                by_alias=True, exclude_none=True
            ),
            "serverInfo": {
                "name": init_options.server_name,
                "version": init_options.server_version,
            },
            "instructions": init_options.instructions,
        }
    elif method == "tools/list":
        tools = await mcp.list_tools()
        result = {
            "tools": [
                tool.model_dump(by_alias=True, exclude_none=True) for tool in tools
            ]
        }
    elif method == "tools/call":
        if not isinstance(params, dict):
            return _json_error(
                types.INVALID_PARAMS, "params must be an object", request_id
            )
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return _json_error(
                types.INVALID_PARAMS, "params.name is required", request_id
            )
        if not isinstance(arguments, dict):
            return _json_error(
                types.INVALID_PARAMS, "params.arguments must be an object", request_id
            )
        content = await mcp.call_tool(name, arguments)
        result = {
            "content": [
                item.model_dump(by_alias=True, exclude_none=True)
                if hasattr(item, "model_dump")
                else item
                for item in content
            ],
            "isError": False,
        }
    else:
        return _json_error(types.METHOD_NOT_FOUND, "Method not found", request_id)

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        },
        media_type="application/json",
    )


async def sse_route(request: Request):
    if request.method == "POST":
        return await handle_jsonrpc(request)
    # SSE initialization frame for legacy clients
    async def event_generator():
        yield {
            "event": "message",
            "data": json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": True},
                        "serverInfo": {"name": "whatsapp", "version": "1.0.0"},
                    },
                }
            ),
        }
        while True:
            await asyncio.sleep(10)

    return EventSourceResponse(event_generator())


app = Starlette(
    routes=[
        Route("/sse", sse_route, methods=["GET", "POST", "HEAD", "OPTIONS"]),
        Route("/mcp", handle_jsonrpc, methods=["POST", "HEAD", "OPTIONS"]),
        Route(
            "/",
            lambda _ : JSONResponse(
                {
                    "name": "whatsapp",
                    "protocolVersion": "2024-11-05",
                    "transport": {"type": "sse", "endpoint": "/sse"},
                },
                media_type="application/json",
            ),
            methods=["GET"],
        ),
        Route(
            "/",
            lambda _ : JSONResponse(
                {
                    "name": "whatsapp",
                    "protocolVersion": "2024-11-05",
                    "transport": {"type": "sse", "endpoint": "/sse"},
                },
                media_type="application/json",
            ),
            methods=["POST"],
        ),
        Route(
            "/.well-known/openid-configuration",
            lambda _ : JSONResponse(
                {
                    "issuer": "http://localhost:3333",
                    "authorization_endpoint": "",
                    "token_endpoint": "",
                    "jwks_uri": "",
                    "response_types_supported": [],
                    "subject_types_supported": ["public"],
                    "id_token_signing_alg_values_supported": [],
                },
                media_type="application/json",
            ),
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            lambda _ : JSONResponse(
                {
                    "issuer": "http://localhost:3333",
                    "authorization_endpoint": "",
                    "token_endpoint": "",
                    "response_types_supported": [],
                    "grant_types_supported": [],
                },
                media_type="application/json",
            ),
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-protected-resource",
            lambda _ : JSONResponse(
                {
                    "resource": "whatsapp-mcp",
                    "authorization_servers": [],
                },
                media_type="application/json",
            ),
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-protected-resource/sse",
            lambda _ : JSONResponse(
                {
                    "resource": "whatsapp-mcp",
                    "authorization_servers": [],
                },
                media_type="application/json",
            ),
            methods=["GET"],
        ),
        Route(
            "/register",
            lambda _ : JSONResponse(
                {
                    "client_id": "poke",
                    "client_secret": "not-required",
                },
                media_type="application/json",
            ),
            methods=["POST"],
        ),
        Route(
            "/.well-known/mcp.json",
            lambda _ : JSONResponse(
                {
                    "name": "whatsapp",
                    "protocolVersion": "2024-11-05",
                    "transport": {"type": "sse", "endpoint": "/sse"},
                },
                media_type="application/json",
            ),
            methods=["GET"],
        ),
    ]
)


if __name__ == "__main__":
    print(f"Streamable HTTP MCP listening on http://localhost:{mcp.settings.port}/sse")
    uvicorn.run(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
