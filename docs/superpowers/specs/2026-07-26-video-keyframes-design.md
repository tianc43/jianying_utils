# Video Keyframes Design

## Goal

Make the existing JianYing Utils keyframe API write usable video keyframes to
API-created drafts after their segments have been saved and reloaded.

## Verified Current Failure

The current API path was reproduced with an isolated temporary draft:

1. `DraftManager.create_draft()` succeeded.
2. `TrackManager.add_track(..., "video", "main")` succeeded.
3. `VideoTool.add_video()` succeeded and returned a segment ID.
4. `KeyframeTool.add_keyframe()` returned `未找到片段 <segment-id>`.

`_context.save_script()` moves saved segments into `script.imported_tracks`.
`keyframe_tool._find_segment()` recognizes a matching imported segment but
returns `None`, so both existing keyframe endpoints fail on the normal
cross-request workflow.

## Reverse-Engineered Contract

The authorized JianYing sample stores video keyframes at:

```text
tracks[type="video"].segments[].common_keyframes[]
```

It does not use the draft's top-level `keyframes` object. A property container
has this shape:

```json
{
  "id": "<uuid>",
  "keyframe_list": [],
  "material_id": "",
  "property_type": "KFTypeScaleX"
}
```

Each linear keyframe has this shape:

```json
{
  "curveType": "Line",
  "graphID": "",
  "id": "<uuid>",
  "left_control": {"x": 0.0, "y": 0.0},
  "right_control": {"x": 0.0, "y": 0.0},
  "time_offset": 1000000,
  "values": [1.2]
}
```

`time_offset` is relative to the segment start and uses microseconds. JianYing
may omit `time_offset` when it is zero; the API may serialize an explicit zero
because both forms have the same meaning.

The supplied sample directly confirms `KFTypeScaleX`. Existing
`pyJianYingDraft.KeyframeProperty` values remain the source for the other
already-advertised property names. `uniform_scale` is serialized as
`KFTypeScaleX`, matching the dependency's existing behavior.

## Architecture

Keep the existing routes and request models:

- `POST /drafts/{draft_id}/keyframes`
- `POST /drafts/{draft_id}/keyframes/batch`

Keep the current object-based path for editable in-memory segments. Add one
focused raw-data path for saved/imported segments:

1. Find the segment in `script.imported_tracks`.
2. Find or create the `common_keyframes` container for the requested
   `property_type`.
3. Append the new linear keyframe and sort the list by `time_offset`, treating
   an omitted offset as zero.
4. Synchronize both the imported track's `raw_data` and its imported segment
   wrapper before calling the existing save path.

No new endpoint, dependency, abstraction layer, or draft format is introduced.

## API Behavior

The single-keyframe request remains:

```json
{
  "segment_id": "<segment-id>",
  "property_name": "uniform_scale",
  "time_offset": "1s",
  "value": 1.2
}
```

The batch request accepts the documented `time_offset` field. It also accepts
the legacy implementation's `offset` field so existing callers do not regress.
If neither field is present, that batch item is not written.

For a single-keyframe request, an unsupported property name, unknown segment
ID, or malformed time string returns a failed result through the existing
error/result wrapper.

For a batch request, unsupported properties, unknown segments, missing or
malformed time values, and nonnumeric or nonfinite values are skipped per item.
Valid neighbors are still written in time order and the successful response's
`count` is reduced to the number actually persisted. Existing audio-volume
handling remains unchanged.

## Validation

Automated tests will cover:

- the currently failing API-created-draft flow;
- creating a new imported-segment property container;
- appending to an existing property and sorting by time;
- `uniform_scale` serialization to `KFTypeScaleX`;
- batch `time_offset` and legacy `offset` inputs;
- the existing test suite.

The end-to-end acceptance check will create an isolated draft through the
existing API tools, add a video segment, add scale keyframes in later calls,
save, reload the JSON, and verify the resulting `common_keyframes` structure.
The produced plaintext will also be encrypted and decrypted with `jy-draftc`
to verify a lossless round trip. The user's original draft will not be edited.

## Later

- Editing or deleting existing keyframes.
- Bezier curves and custom control points.
- Loading current JianYing 10.x encrypted drafts directly through the older
  `pyJianYingDraft` template loader.
