"""Bound request bodies before JSON parsing, including streamed requests."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_response

MAX_BODY_BYTES = 32 * 1024


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        lengths = [value for key, value in scope["headers"] if key.lower() == b"content-length"]
        for value in lengths:
            if not value.isdigit():
                response = error_response(422, "VALIDATION_ERROR", "Invalid Content-Length")
                await response(scope, receive, send)
                return
            # Avoid converting unbounded integers from untrusted headers.
            normalized = value.lstrip(b"0") or b"0"
            if len(normalized) > len(str(self.max_bytes)) or int(normalized) > self.max_bytes:
                await self._reject(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = error_response(413, "PAYLOAD_TOO_LARGE", "Request body exceeds 32 KiB")
        await response(scope, receive, send)


class ConfiguredCORSMiddleware:
    """Read CORS after startup settings are validated, never at module import."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.delegate: ASGIApp | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self.delegate is None:
            from starlette.middleware.cors import CORSMiddleware

            origins = scope["app"].state.settings.cors_origins
            self.delegate = CORSMiddleware(
                self.app,
                allow_origins=origins,
                allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                allow_headers=["Authorization", "Content-Type", "X-API-Key"],
            ) if origins else self.app
        await self.delegate(scope, receive, send)
