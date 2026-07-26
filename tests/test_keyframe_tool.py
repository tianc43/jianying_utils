import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from jianying_utils import _context
from jianying_utils.draft_manager import DraftManager
from jianying_utils.keyframe_tool import KeyframeTool
from jianying_utils.track_manager import TrackManager
from jianying_utils.video_tool import VideoTool


class KeyframeToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.draft_name = "keyframe-test"
        self.media_path = self.root / "source.webp"
        Image.new("RGB", (16, 16), (255, 0, 0)).save(self.media_path, "WEBP")

        created = DraftManager.create_draft(str(self.root), self.draft_name)
        self.assertTrue(created["success"], created)
        tracked = TrackManager.add_track(
            str(self.root), self.draft_name, "video", "main"
        )
        self.assertTrue(tracked["success"], tracked)
        added = VideoTool.add_video(
            str(self.root),
            self.draft_name,
            str(self.media_path),
            "0s",
            "5s",
            track_name="main",
        )
        self.assertTrue(added["success"], added)
        self.segment_id = added["segment_id"]
        _context.clear_session(str(self.root), self.draft_name)

    def tearDown(self) -> None:
        _context.clear_session(str(self.root), self.draft_name)
        self.temp_dir.cleanup()

    def _saved_segment(self) -> dict:
        draft_path = self.root / self.draft_name / "draft_content.json"
        content = json.loads(draft_path.read_text(encoding="utf-8"))
        return next(
            segment
            for track in content["tracks"]
            for segment in track["segments"]
            if segment["id"] == self.segment_id
        )

    def test_adds_and_sorts_uniform_scale_keyframes_on_saved_segment(self) -> None:
        later = KeyframeTool.add_keyframe(
            str(self.root),
            self.draft_name,
            self.segment_id,
            "uniform_scale",
            "2s",
            1.4,
        )
        self.assertTrue(later["success"], later)
        first_container_id = self._saved_segment()["common_keyframes"][0]["id"]
        _context.clear_session(str(self.root), self.draft_name)

        earlier = KeyframeTool.add_keyframe(
            str(self.root),
            self.draft_name,
            self.segment_id,
            "uniform_scale",
            500_000,
            1.1,
        )

        self.assertTrue(earlier["success"], earlier)
        containers = self._saved_segment()["common_keyframes"]
        self.assertEqual(len(containers), 1)
        self.assertEqual(containers[0]["id"], first_container_id)
        self.assertEqual(containers[0]["property_type"], "KFTypeScaleX")
        self.assertEqual(containers[0]["material_id"], "")
        self.assertEqual(
            [item["time_offset"] for item in containers[0]["keyframe_list"]],
            [500_000, 2_000_000],
        )
        self.assertEqual(
            [item["values"] for item in containers[0]["keyframe_list"]],
            [[1.1], [1.4]],
        )
        for item in containers[0]["keyframe_list"]:
            self.assertEqual(item["curveType"], "Line")
            self.assertEqual(item["graphID"], "")
            self.assertEqual(item["left_control"], {"x": 0.0, "y": 0.0})
            self.assertEqual(item["right_control"], {"x": 0.0, "y": 0.0})

    def test_batch_accepts_documented_and_legacy_offset_fields(self) -> None:
        result = KeyframeTool.add_keyframes_batch(
            str(self.root),
            self.draft_name,
            [
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1s",
                    "value": 0.25,
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "offset": 2_000_000,
                    "value": 0.5,
                },
            ],
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["count"], 2)
        container = next(
            item
            for item in self._saved_segment()["common_keyframes"]
            if item["property_type"] == "KFTypePositionX"
        )
        self.assertEqual(
            [item["time_offset"] for item in container["keyframe_list"]],
            [1_000_000, 2_000_000],
        )
        self.assertEqual(
            [item["values"] for item in container["keyframe_list"]],
            [[0.25], [0.5]],
        )

    def test_batch_preserves_documented_time_forms(self) -> None:
        time_values = ("250000", "0.5s", "5s", "1m30s", "1h2m3s")
        result = KeyframeTool.add_keyframes_batch(
            str(self.root),
            self.draft_name,
            [
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": time_value,
                    "value": index / 10,
                }
                for index, time_value in enumerate(time_values, start=1)
            ],
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["count"], len(time_values))
        container = next(
            item
            for item in self._saved_segment()["common_keyframes"]
            if item["property_type"] == "KFTypePositionX"
        )
        self.assertEqual(
            [item["time_offset"] for item in container["keyframe_list"]],
            [250_000, 500_000, 5_000_000, 90_000_000, 3_723_000_000],
        )

    def test_batch_skips_malformed_time_offsets(self) -> None:
        result = KeyframeTool.add_keyframes_batch(
            str(self.root),
            self.draft_name,
            [
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1s",
                    "value": 0.25,
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "garbage",
                    "value": 0.4,
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "",
                    "value": 0.45,
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1sfoo",
                    "value": 0.475,
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "2s",
                    "value": 0.5,
                },
            ],
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["count"], 2)
        container = next(
            item
            for item in self._saved_segment()["common_keyframes"]
            if item["property_type"] == "KFTypePositionX"
        )
        self.assertEqual(
            [item["time_offset"] for item in container["keyframe_list"]],
            [1_000_000, 2_000_000],
        )
        self.assertEqual(
            [item["values"] for item in container["keyframe_list"]],
            [[0.25], [0.5]],
        )

    def test_single_rejects_malformed_time_offsets(self) -> None:
        for malformed in ("garbage", "", "1sfoo"):
            with self.subTest(time_offset=malformed):
                result = KeyframeTool.add_keyframe(
                    str(self.root),
                    self.draft_name,
                    self.segment_id,
                    "position_x",
                    malformed,
                    0.25,
                )
                self.assertFalse(result["success"], result)
                _context.clear_session(str(self.root), self.draft_name)

        self.assertEqual(self._saved_segment()["common_keyframes"], [])

    def test_saved_visual_axis_keyframes_disable_uniform_scale(self) -> None:
        for property_name in ("scale_x", "scale_y"):
            result = KeyframeTool.add_keyframe(
                str(self.root),
                self.draft_name,
                self.segment_id,
                property_name,
                "1s",
                1.2,
            )

            self.assertTrue(result["success"], result)
            self.assertFalse(self._saved_segment()["uniform_scale"]["on"])
            _context.clear_session(str(self.root), self.draft_name)

    def test_saved_visual_uniform_scale_fails_in_axis_mode(self) -> None:
        axis = KeyframeTool.add_keyframe(
            str(self.root),
            self.draft_name,
            self.segment_id,
            "scale_x",
            "1s",
            1.2,
        )
        self.assertTrue(axis["success"], axis)
        _context.clear_session(str(self.root), self.draft_name)
        before = self._saved_segment()

        uniform = KeyframeTool.add_keyframe(
            str(self.root),
            self.draft_name,
            self.segment_id,
            "uniform_scale",
            "2s",
            1.4,
        )

        self.assertFalse(uniform["success"], uniform)
        self.assertEqual(self._saved_segment(), before)

    def test_batch_skips_non_json_numeric_values(self) -> None:
        result = KeyframeTool.add_keyframes_batch(
            str(self.root),
            self.draft_name,
            [
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1s",
                    "value": 0.25,
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1.1s",
                    "value": False,
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1.2s",
                    "value": None,
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1.3s",
                    "value": "0.4",
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1.4s",
                    "value": float("nan"),
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1.5s",
                    "value": float("inf"),
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "1.6s",
                    "value": float("-inf"),
                },
                {
                    "segment_id": self.segment_id,
                    "property": "position_x",
                    "time_offset": "2s",
                    "value": 0.5,
                },
            ],
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["count"], 2)
        container = next(
            item
            for item in self._saved_segment()["common_keyframes"]
            if item["property_type"] == "KFTypePositionX"
        )
        self.assertEqual(
            [item["time_offset"] for item in container["keyframe_list"]],
            [1_000_000, 2_000_000],
        )
        self.assertEqual(
            [item["values"] for item in container["keyframe_list"]],
            [[0.25], [0.5]],
        )


if __name__ == "__main__":
    unittest.main()
