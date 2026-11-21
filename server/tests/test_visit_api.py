# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The Visitors view's downloads: what a visitor gets, and in which words."""

import errno
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nocs.api.visit import visit_router
from nocs.imaging.pictures import NothingToShowError, Picture


class Pictures:
    def __init__(self, answer: Callable[[], Picture]) -> None:
        self.answer = answer

    async def frame(self) -> Picture:
        return self.answer()

    async def stack(self) -> Picture:
        return self.answer()


def client(answer: Callable[[], Picture]) -> TestClient:
    app = FastAPI()
    pictures = Pictures(answer)
    app.include_router(visit_router(lambda: pictures))  # pyright: ignore[reportArgumentType]
    return TestClient(app, raise_server_exceptions=False)


def raises(error: Exception) -> Callable[[], Picture]:
    def answer() -> Picture:
        raise error

    return answer


def test_a_picture_is_a_download(tmp_path: Path) -> None:
    jpeg = tmp_path / "stack-x.jpg"
    jpeg.write_bytes(b"jpeg")
    response = client(lambda: Picture(jpeg, "NOCS_M_42_20261121_030405.jpg")).get(
        "/api/visit/stack.jpg"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert 'filename="NOCS_M_42_20261121_030405.jpg"' in response.headers["content-disposition"]
    assert response.content == b"jpeg"


@pytest.mark.parametrize(
    ("error", "code", "detail"),
    [
        (NothingToShowError("no stack yet"), 404, "no stack yet"),
        (OSError(errno.ENOSPC, "No space left", "/media/x/NOCS/a.fits"), 507, "the box is full"),
        (
            OSError(errno.EXDEV, "Invalid cross-device link", "/media/x/a.fits"),
            500,
            "the picture could not be made",
        ),
        (ValueError("JPEG encoding failed"), 500, "the picture could not be made"),
    ],
)
def test_what_went_wrong_says_no_path(error: Exception, code: int, detail: str) -> None:
    response = client(raises(error)).get("/api/visit/frame.jpg")
    assert response.status_code == code
    assert response.json()["detail"] == detail
