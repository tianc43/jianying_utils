from fastapi import HTTPException
from fastapi.testclient import TestClient

import jianying_utils.server as server


def _request(**updates):
    values = {
        "endpoint_url": "https://example.com/v1/images/generations",
        "prompt": "unsafe original prompt",
        "client_job_key": "workflow-run-storyboard-5",
        "wait_timeout_seconds": 0,
    }
    values.update(updates)
    return server.ImageGenerateJobWaitRequest(**values)


def test_wait_returns_permanent_failure_as_structured_terminal(monkeypatch):
    failed_job = {
        "job_id": "original-job",
        "status": "failed",
        "message": "图片生成任务失败",
        "error": '上游返回: {"error":{"code":"invalid_request"}}',
    }
    monkeypatch.setattr(server, "_submit_image_job", lambda body, key: failed_job)

    result = server.material_generate_image_job_wait(_request())

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["failure_code"] == "invalid_request"
    assert result["job_id"] == "original-job"


def test_wait_endpoint_serializes_terminal_failure_with_http_200(monkeypatch):
    monkeypatch.setattr(
        server,
        "_submit_image_job",
        lambda body, key: {
            "job_id": "failed-job",
            "status": "failed",
            "message": "图片生成任务失败",
            "error": '上游返回: {"error":{"code":"invalid_request"}}',
        },
    )

    response = TestClient(server.app).post(
        "/material/images/generate/jobs/wait",
        json={
            "endpoint_url": "https://example.com/v1/images/generations",
            "prompt": "test prompt",
            "client_job_key": "terminal-contract-test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    assert payload["failure_code"] == "invalid_request"


def test_content_policy_failure_uses_safe_prompt_once(monkeypatch):
    calls = []
    original_failed = {
        "job_id": "original-job",
        "status": "failed",
        "message": "图片生成任务失败",
        "error": '上游返回: {"error":{"code":"content_policy_violation"}}',
    }
    safe_succeeded = {
        "job_id": "safe-job",
        "status": "succeeded",
        "message": "图片生成任务已完成",
        "error": "",
        "result": {
            "success": True,
            "image_url": "https://example.com/safe.webp",
            "static_url": "https://example.com/safe.webp",
        },
    }

    def fake_submit(body, key):
        calls.append((body.prompt, key))
        return safe_succeeded if key.endswith("::safe-retry-1") else original_failed

    monkeypatch.setattr(server, "_submit_image_job", fake_submit)

    result = server.material_generate_image_job_wait(
        _request(safe_prompt="gentle symbolic ribbon trailing out of frame", safe_retry_count=1)
    )

    assert calls == [
        ("unsafe original prompt", "workflow-run-storyboard-5"),
        ("gentle symbolic ribbon trailing out of frame", "workflow-run-storyboard-5::safe-retry-1"),
    ]
    assert result["success"] is True
    assert result["status"] == "succeeded"
    assert result["terminal"] is True
    assert result["safe_retry_used"] is True
    assert result["original_job_id"] == "original-job"
    assert result["job_id"] == "safe-job"


def test_safe_retry_still_uses_425_while_running(monkeypatch):
    original_failed = {
        "job_id": "original-job",
        "status": "failed",
        "message": "图片生成任务失败",
        "error": 'content_policy_violation',
    }
    safe_running = {
        "job_id": "safe-job",
        "status": "running",
        "message": "图片生成任务运行中",
        "error": "",
    }

    def fake_submit(body, key):
        return safe_running if key.endswith("::safe-retry-1") else original_failed

    monkeypatch.setattr(server, "_submit_image_job", fake_submit)

    try:
        server.material_generate_image_job_wait(
            _request(safe_prompt="safe prompt", safe_retry_count=1)
        )
    except HTTPException as exc:
        assert exc.status_code == server._IMAGE_JOB_POLL_STATUS
        assert exc.detail["job_id"] == "safe-job"
        assert exc.detail["safe_retry_used"] is True
    else:
        raise AssertionError("running safe retry should return the polling status")
