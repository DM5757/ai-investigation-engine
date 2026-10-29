"""Application error hierarchy mapped to stable API error codes."""

from __future__ import annotations


class AppError(Exception):
    """Base application error."""

    code: str = "app_error"
    http_status: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedFormat(AppError):
    code = "unsupported_format"
    http_status = 400


class ParseError(AppError):
    code = "parse_error"
    http_status = 400


class DuplicateDocument(AppError):
    code = "duplicate_document"
    http_status = 409


class IndexSyncError(AppError):
    code = "index_sync_error"
    http_status = 500


class LLMUnavailable(AppError):
    code = "llm_unavailable"
    http_status = 503


class LLMOutputInvalid(AppError):
    code = "llm_output_invalid"
    http_status = 502


class BudgetExceeded(AppError):
    code = "budget_exceeded"
    http_status = 429


class NotFound(AppError):
    code = "not_found"
    http_status = 404


class Unauthorized(AppError):
    code = "unauthorized"
    http_status = 401
