# Video Keyframes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing keyframe API add video keyframes to saved API-created segments and preserve them in JianYing's native `common_keyframes` structure.

**Architecture:** Preserve the current object-based path for editable segments and add a focused raw-dictionary path for segments stored in `script.imported_tracks`. Both the single and batch APIs share the raw writer, and the existing `_context.save_script()` remains the only persistence boundary.

**Tech Stack:** Python 3, `pyjianyingdraft==0.2.6`, standard-library `unittest`, Pillow, `jy-draftc`

## Global Constraints

- Keep `POST /drafts/{draft_id}/keyframes` and `POST /drafts/{draft_id}/keyframes/batch` unchanged.
- Store keyframes only in `tracks[].segments[].common_keyframes`; do not use the draft-level `keyframes` object.
- Interpret keyframe offsets as segment-relative microseconds, including supported time strings such as `"1s"`.
- Serialize `uniform_scale` as `KFTypeScaleX`.
- Preserve the existing audio-volume path.
- Do not edit the user's original draft.
- Do not implement keyframe update/delete operations or Bezier controls.

---

## File Structure

- Create `tests/test_keyframe_tool.py`: behavioral regression tests using real API-created drafts.
- Modify `jianying_utils/keyframe_tool.py`: imported-segment lookup, native JSON keyframe construction, and batch input compatibility.

### Task 1: Restore single video keyframes on saved segments

**Files:**
- Create: `tests/test_keyframe_tool.py`
- Modify: `jianying_utils/keyframe_tool.py:6`
- Modify: `jianying_utils/keyframe_tool.py:57`
- Modify: `jianying_utils/keyframe_tool.py:174`

**Interfaces:**
- Consumes: `KeyframeTool.add_keyframe(folder_path, draft_name, segment_id, property_name, time_offset, value)`
- Produces: `_add_imported_keyframe(script, segment_id, prop, time_offset, value) -> bool`

- [ ] **Step 1: Write the failing saved-segment regression test**

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify the current failure**

Run:

```powershell
python -X utf8 -m unittest discover -s tests -p "test_keyframe_tool.py" -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: `FAIL` because `KeyframeTool.add_keyframe()` returns
`{"success": false, "message": "未找到片段 ..."}`.

- [ ] **Step 3: Add the imported-segment keyframe writer**

Add `from uuid import uuid4` beside the imports in
`jianying_utils/keyframe_tool.py`, parse the offset before choosing the object
or imported path, and use the new helper when `_find_segment()` returns
`None`:

```python
        prop = _PROPERTY_MAP[property_name]
        offset = _parse_time(time_offset)
        segment = _find_segment(script, segment_id)

        if segment is None:
            if not _add_imported_keyframe(
                script, segment_id, prop, offset, value
            ):
                return _context.make_result(False, f"未找到片段 {segment_id}")
        elif prop == KeyframeProperty.volume and isinstance(segment, AudioSegment):
            segment.add_keyframe(offset, value)
        else:
            segment.add_keyframe(prop, offset, value)

        _context.save_script(script)
```

Add these helpers after `_find_segment()`:

```python
def _raw_property_type(prop: KeyframeProperty) -> str:
    if prop == KeyframeProperty.uniform_scale:
        return KeyframeProperty.scale_x.value
    return prop.value


def _add_imported_keyframe(
    script,
    segment_id: str,
    prop: KeyframeProperty,
    time_offset: int,
    value: float,
) -> bool:
    """Attach a linear keyframe to an already-saved/imported segment."""
    seg_data = None
    seg_obj = None
    for imp_track in script.imported_tracks:
        for index, item in enumerate(imp_track.raw_data.get("segments", [])):
            if item.get("id") == segment_id:
                seg_data = item
                if hasattr(imp_track, "segments") and index < len(imp_track.segments):
                    seg_obj = imp_track.segments[index]
                break
        if seg_data is not None:
            break
    if seg_data is None:
        return False

    property_type = _raw_property_type(prop)
    containers = seg_data.setdefault("common_keyframes", [])
    container = next(
        (
            item
            for item in containers
            if item.get("property_type") == property_type
        ),
        None,
    )
    if container is None:
        container = {
            "id": uuid4().hex,
            "keyframe_list": [],
            "material_id": "",
            "property_type": property_type,
        }
        containers.append(container)

    container.setdefault("keyframe_list", []).append(
        {
            "curveType": "Line",
            "graphID": "",
            "id": uuid4().hex,
            "left_control": {"x": 0.0, "y": 0.0},
            "right_control": {"x": 0.0, "y": 0.0},
            "time_offset": time_offset,
            "values": [value],
        }
    )
    container["keyframe_list"].sort(
        key=lambda item: int(item.get("time_offset") or 0)
    )
    if seg_obj is not None:
        seg_obj.raw_data = seg_data
    return True
```

- [ ] **Step 4: Run the focused test and the baseline suite**

Run:

```powershell
python -X utf8 -m unittest discover -s tests -p "test_keyframe_tool.py" -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -X utf8 -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: the focused keyframe test and all four existing baseline tests pass.

- [ ] **Step 5: Commit the single-keyframe fix**

```powershell
git add -- jianying_utils/keyframe_tool.py tests/test_keyframe_tool.py
git diff --cached --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git commit -m "fix: write keyframes to saved video segments"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

### Task 2: Make the batch endpoint honor its documented offset field

**Files:**
- Modify: `tests/test_keyframe_tool.py`
- Modify: `jianying_utils/keyframe_tool.py:105`

**Interfaces:**
- Consumes: `KeyframeTool.add_keyframes_batch(folder_path, draft_name, keyframes)`
- Produces: support for both `time_offset` and legacy `offset` per batch item

- [ ] **Step 1: Add a failing batch compatibility test**

Add this method to `KeyframeToolTests`:

```python
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
```

- [ ] **Step 2: Run the batch test and verify the current failure**

Run:

```powershell
python -X utf8 -m unittest discover -s tests -p "test_keyframe_tool.py" -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: `FAIL`; the current implementation reads only `offset` and cannot
write the saved segment.

- [ ] **Step 3: Route batch items through the shared imported writer**

Replace the body of the `for kf in keyframes:` loop with:

```python
        for kf in keyframes:
            seg_id = kf.get("segment_id")
            prop_name = kf.get("property")
            offset_value = kf.get("time_offset", kf.get("offset"))
            if (
                not seg_id
                or prop_name not in _PROPERTY_MAP
                or offset_value is None
                or "value" not in kf
            ):
                continue

            offset = _parse_time(offset_value)
            value = kf["value"]
            prop = _PROPERTY_MAP[prop_name]
            segment = _find_segment(script, seg_id)

            if segment is None:
                if not _add_imported_keyframe(
                    script, seg_id, prop, offset, value
                ):
                    continue
            elif prop == KeyframeProperty.volume and isinstance(segment, AudioSegment):
                segment.add_keyframe(offset, value)
            else:
                segment.add_keyframe(prop, offset, value)
            count += 1
```

- [ ] **Step 4: Run all keyframe and repository tests**

Run:

```powershell
python -X utf8 -m unittest discover -s tests -p "test_keyframe_tool.py" -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -X utf8 -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -X utf8 -m compileall -q jianying_utils tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: two keyframe tests and the complete repository suite pass;
`compileall` and `git diff --check` exit zero.

- [ ] **Step 5: Commit batch compatibility**

```powershell
git add -- jianying_utils/keyframe_tool.py tests/test_keyframe_tool.py
git diff --cached --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git commit -m "fix: accept documented batch keyframe offsets"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

### Task 3: Verify a real saved draft and encryption round trip

**Files:**
- Verify: generated temporary draft outside the repository

**Interfaces:**
- Consumes: the repaired `KeyframeTool` and `D:\jy-draftc-amd64-windows\jy-draftc.exe`
- Produces: plaintext JSON evidence and a byte-identical decrypt round trip

- [ ] **Step 1: Create and keyframe an isolated API draft**

Run this PowerShell block:

```powershell
$validationRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    "codex-keyframe-acceptance-" + [guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $validationRoot -Force | Out-Null
$validationScript = @'
import json
import sys
from pathlib import Path
from PIL import Image
from jianying_utils.draft_manager import DraftManager
from jianying_utils.track_manager import TrackManager
from jianying_utils.video_tool import VideoTool
from jianying_utils.keyframe_tool import KeyframeTool

root = Path(sys.argv[1])
name = "acceptance"
media = root / "source.webp"
Image.new("RGB", (32, 32), (0, 128, 255)).save(media, "WEBP")
assert DraftManager.create_draft(str(root), name)["success"]
assert TrackManager.add_track(str(root), name, "video", "main")["success"]
added = VideoTool.add_video(
    str(root), name, str(media), "0s", "5s", track_name="main"
)
assert added["success"], added
segment_id = added["segment_id"]
assert KeyframeTool.add_keyframe(
    str(root), name, segment_id, "uniform_scale", 0, 1.0
)["success"]
assert KeyframeTool.add_keyframe(
    str(root), name, segment_id, "uniform_scale", "5s", 1.5
)["success"]
content_path = root / name / "draft_content.json"
content = json.loads(content_path.read_text(encoding="utf-8"))
segment = next(
    segment
    for track in content["tracks"]
    for segment in track["segments"]
    if segment["id"] == segment_id
)
container = segment["common_keyframes"][0]
assert container["property_type"] == "KFTypeScaleX"
assert [item["time_offset"] for item in container["keyframe_list"]] == [
    0,
    5_000_000,
]
print(json.dumps({"draft": str(content_path), "segment_id": segment_id}))
'@
$validationJson = python -X utf8 -c $validationScript $validationRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$validation = $validationJson | ConvertFrom-Json
```

Expected: the script exits zero and `$validation.draft` points to a plaintext
draft containing two `KFTypeScaleX` frames.

- [ ] **Step 2: Encrypt, decrypt, and compare the generated draft**

Run:

```powershell
$draftPlain = [string]$validation.draft
$draftEncrypted = Join-Path $validationRoot "draft_content.encrypted.json"
$draftRoundTrip = Join-Path $validationRoot "draft_content.roundtrip.json"
$draftc = "D:\jy-draftc-amd64-windows\jy-draftc.exe"
& $draftc -e $draftPlain $draftEncrypted
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $draftc -d $draftEncrypted $draftRoundTrip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$plainHash = (Get-FileHash -LiteralPath $draftPlain -Algorithm SHA256).Hash
$roundTripHash = (Get-FileHash -LiteralPath $draftRoundTrip -Algorithm SHA256).Hash
if ($plainHash -ne $roundTripHash) {
    throw "Keyframe draft encryption round trip changed the plaintext"
}
[ordered]@{
    draft = $draftPlain
    encrypted = $draftEncrypted
    roundtrip = $draftRoundTrip
    sha256 = $plainHash
} | ConvertTo-Json
```

Expected: `jy-draftc` encryption and decryption both exit zero, and the two
SHA-256 values are identical.

- [ ] **Step 3: Run the final pre-delivery checks**

Run:

```powershell
python -X utf8 -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -X utf8 -m compileall -q jianying_utils tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git status --short
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Expected: the complete test suite passes, compilation succeeds, and only
intentional plan/implementation changes are present.
