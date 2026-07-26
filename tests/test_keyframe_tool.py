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
        earlier = KeyframeTool.add_keyframe(
            str(self.root),
            self.draft_name,
            self.segment_id,
            "uniform_scale",
            500_000,
            1.1,
        )

        self.assertTrue(later["success"], later)
        self.assertTrue(earlier["success"], earlier)
        containers = self._saved_segment()["common_keyframes"]
        self.assertEqual(len(containers), 1)
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
                    "time_offset": "not-a-time",
                    "value": 0.4,
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
