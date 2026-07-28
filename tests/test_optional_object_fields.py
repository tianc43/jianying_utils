import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jianying_utils.server import (
    CaptionsAdd,
    ImageGenerateRequest,
    TextAdd,
    VideoAdd,
    app,
)


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            '{"transform_x": -0.8, "transform_y": 0.87}',
            {"transform_x": -0.8, "transform_y": 0.87},
        ),
        (
            "{'transform_x': -0.8, 'transform_y': 0.87}",
            {"transform_x": -0.8, "transform_y": 0.87},
        ),
    ],
)
def test_optional_object_accepts_dify_stringified_dictionaries(value, expected):
    model = TextAdd(
        text="账号角标",
        start="0s",
        duration="1s",
        clip_settings=value,
    )

    assert model.clip_settings == expected


def test_all_public_optional_object_models_use_the_same_parser():
    video = VideoAdd(
        video_path="https://example.com/image.png",
        start="0s",
        glow_outline="{'color': '#FFFFFF', 'size': 10}",
        mask='{"type": "circle"}',
    )
    captions = CaptionsAdd(
        captions=[{"text": "字幕", "start": 0, "end": 1_000_000}],
        border="{'color': '#FFFFFF', 'width': 4}",
    )
    image = ImageGenerateRequest(
        endpoint_url="https://example.com/v1/images/generations",
        prompt="test",
        headers="{'x-test': 'value'}",
        extra_body='{"seed": 1}',
    )

    assert video.glow_outline == {"color": "#FFFFFF", "size": 10}
    assert video.mask == {"type": "circle"}
    assert captions.border == {"color": "#FFFFFF", "width": 4}
    assert image.headers == {"x-test": "value"}
    assert image.extra_body == {"seed": 1}


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


def test_text_endpoint_accepts_dify_python_dictionary_strings():
    response = TestClient(app).post(
        "/drafts/codex-nonexistent/texts",
        json={
            "text": "提示文字",
            "start": "0s",
            "duration": "1s",
            "text_gradient": (
                "{'colors': ['#FFBF17', '#2D5094'], 'alphas': [1, 1], "
                "'percents': [0.949115, 0.283923], 'angle': 0, 'mode': 'all'}"
            ),
            "border": "{'color': '#FFFFFF', 'width': 4, 'alpha': 0.85}",
            "clip_settings": (
                "{'transform_x': 0.65, 'transform_y': 0.87, "
                "'scale_x': 1, 'scale_y': 1}"
            ),
        },
    )

    assert response.status_code == 404
    assert "草稿不存在" in response.json()["detail"]
