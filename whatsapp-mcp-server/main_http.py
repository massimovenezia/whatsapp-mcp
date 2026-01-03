import argparse
import json
import os
import uvicorn
from main import mcp
from mcp import types
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

# Configure HTTP transport defaults for streamable MCP over JSON-RPC
default_host = os.environ.get("HOST", "0.0.0.0")
default_port = int(os.environ.get("PORT", 3333))
mcp.settings.host = default_host
mcp.settings.port = default_port

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


def _accepts_sse(request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "").lower()


async def sse_route(request: Request):
    if request.method == "POST":
        return await handle_jsonrpc(request)
    if _accepts_sse(request):
        return PlainTextResponse(
            "SSE is not available on this endpoint. Use POST with JSON-RPC 2.0.",
            status_code=405,
        )
    return PlainTextResponse(
        "WhatsApp MCP streamable HTTP endpoint. Use POST with application/json.",
        media_type="text/plain",
    )


async def mcp_route(request: Request):
    if request.method == "POST":
        return await handle_jsonrpc(request)
    if _accepts_sse(request):
        return PlainTextResponse(
            "SSE is not available on this endpoint. Use POST with JSON-RPC 2.0.",
            status_code=405,
        )
    return PlainTextResponse(
        "WhatsApp MCP streamable HTTP endpoint. Use POST with application/json.",
        media_type="text/plain",
    )


async def root_route(_: Request):
    return JSONResponse(
        {"name": "whatsapp-mcp", "status": "ok", "mcpEndpoint": "/mcp"},
        media_type="application/json",
    )


async def redirect_mcp(_: Request):
    return RedirectResponse("/mcp", status_code=308)


async def redirect_sse(_: Request):
    return RedirectResponse("/sse", status_code=308)


def _not_found(_: Request):
    return JSONResponse({"error": "not implemented"}, status_code=404)


app = Starlette(
    routes=[
        Route("/sse", sse_route, methods=["GET", "POST", "HEAD", "OPTIONS"]),
        Route("/sse/", redirect_sse, methods=["GET", "HEAD"]),
        Route("/mcp", mcp_route, methods=["GET", "POST", "HEAD", "OPTIONS"]),
        Route("/mcp/", redirect_mcp, methods=["GET", "HEAD"]),
        Route("/", root_route, methods=["GET", "POST", "HEAD"]),
        Route("/.well-known/openid-configuration", _not_found, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", _not_found, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", _not_found, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource/sse", _not_found, methods=["GET"]),
        Route("/register", _not_found, methods=["POST"]),
        Route("/token", _not_found, methods=["GET", "POST"]),
        Route("/authorize", _not_found, methods=["GET", "POST"]),
        Route(
            "/.well-known/mcp.json",
            lambda _ : JSONResponse(
                {
                    "name": "whatsapp",
                    "protocolVersion": "2024-11-05",
                    "transport": {"type": "http", "endpoint": "/mcp"},
                },
                media_type="application/json",
            ),
            methods=["GET"],
        ),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*", "https://poke.com"],
            allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    ],
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args()
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    print(f"Streamable HTTP MCP listening on http://{args.host}:{args.port}/mcp")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=mcp.settings.log_level.lower(),
    )
