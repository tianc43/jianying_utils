import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jianying_utils.server import CaptionsAdd, TextAdd, VideoAdd, app


@pytest.mark.parametrize("blank", ["", "   ", "\t\r\n"])
def test_text_add_treats_blank_optional_objects_as_none(blank):
    model = TextAdd(
        text="账号角标",
        start="0s",
        duration="1s",
        text_gradient=blank,
        border=blank,
        background=blank,
        shadow=blank,
        clip_settings=blank,
    )

    assert model.text_gradient is None
    assert model.border is None
    assert model.background is None
    assert model.shadow is None
    assert model.clip_settings is None


def test_caption_and_video_add_treat_blank_optional_objects_as_none():
    captions = CaptionsAdd(
        captions=[{"text": "字幕", "start": 0, "end": 1_000_000}],
        border="",
        clip_settings=" ",
    )
    video = VideoAdd(
        video_path="https://example.com/image.png",
        start="0s",
        clip_settings="",
        mask=" ",
        background_filling="\t",
    )

    assert captions.border is None
    assert captions.clip_settings is None
    assert video.clip_settings is None
    assert video.mask is None
    assert video.background_filling is None


def test_optional_object_dictionary_is_preserved():
    clip_settings = {"transform_x": -0.8, "transform_y": 0.87}

    model = TextAdd(
        text="账号角标",
        start="0s",
        duration="1s",
        clip_settings=clip_settings,
    )

    assert model.clip_settings == clip_settings


def test_non_blank_optional_object_string_remains_invalid():
    with pytest.raises(ValidationError):
        TextAdd(
            text="账号角标",
            start="0s",
            duration="1s",
            clip_settings="not-an-object",
        )


def test_text_endpoint_accepts_dify_blank_optional_objects():
    response = TestClient(app).post(
        "/drafts/codex-nonexistent/texts",
        json={
            "text": "账号角标",
            "start": "0s",
            "duration": "1s",
            "border": "",
            "clip_settings": "",
        },
    )

    assert response.status_code == 404
    assert "草稿不存在" in response.json()["detail"]
