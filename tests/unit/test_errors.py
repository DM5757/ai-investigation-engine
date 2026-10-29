"""Error hierarchy smoke tests."""

from app.errors import NotFound, UnsupportedFormat


def test_error_codes() -> None:
    assert UnsupportedFormat("x").code == "unsupported_format"
    assert UnsupportedFormat("x").http_status == 400
    assert NotFound("missing").http_status == 404
