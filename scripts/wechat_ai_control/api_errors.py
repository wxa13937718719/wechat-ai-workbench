from dataclasses import dataclass, field

from fastapi.responses import JSONResponse


@dataclass
class ApiError(Exception):
    code: str
    message: str
    status_code: int = 400
    retryable: bool = False
    details: dict = field(default_factory=dict)


def error_payload(code, message, retryable=False, details=None):
    return {
        "error": {
            "code": str(code),
            "message": str(message),
            "retryable": bool(retryable),
            "details": dict(details or {}),
        }
    }


def error_response(error: ApiError):
    return JSONResponse(
        error_payload(error.code, error.message, error.retryable, error.details),
        status_code=error.status_code,
    )
