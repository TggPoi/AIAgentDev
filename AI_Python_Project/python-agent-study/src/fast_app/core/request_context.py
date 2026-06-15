from contextvars import ContextVar, Token


REQUEST_ID_HEADER = "X-Request-ID"

request_id_var: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)
trace_id_var: ContextVar[str | None] = ContextVar(
    "trace_id",
    default=None,
)


def get_request_id() -> str | None:
    return request_id_var.get()


def get_trace_id() -> str | None:
    return trace_id_var.get()


def set_request_context(
    request_id: str,
    trace_id: str | None = None,
) -> tuple[Token[str | None], Token[str | None]]:
    request_id_token = request_id_var.set(request_id)
    trace_id_token = trace_id_var.set(trace_id or request_id)
    return request_id_token, trace_id_token


def reset_request_context(
    request_id_token: Token[str | None],
    trace_id_token: Token[str | None],
) -> None:
    request_id_var.reset(request_id_token)
    trace_id_var.reset(trace_id_token)
