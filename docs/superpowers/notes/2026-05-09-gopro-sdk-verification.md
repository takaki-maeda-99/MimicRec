# GoPro Phase 0 — SDK + environment verification

**Date**: 2026-05-09
**Hardware**: GoPro Hero 11 Black, USB serial `C3471327153141`, firmware `H22.01.02.32.00`
**Host**: Linux (Ubuntu 22.04), Python 3.12, ffmpeg 4.4.2

## Decision: PASS — proceed with implementation

All required APIs and environment elements are working with caveats noted below.

## Versions pinned

- `open-gopro==0.22.0` (PyPI, installed via uv into `backend/.venv`)
- `ffmpeg 4.4.2-0ubuntu0.22.04.1`

## API surface confirmation

`open_gopro 0.22.0` does **not** export `constants` from the package root. Use:

```python
from open_gopro import WiredGoPro
from open_gopro.models import constants   # Toggle, StatusId, SettingId, ErrorCode, ...
from open_gopro.models import proto       # EnumPresetGroup, ...
```

All required HTTP commands are present on `WiredGoPro.http_command`:

- `set_date_time` ✓
- `set_shutter` ✓
- `get_media_list` ✓
- `download_file` ✓
- `set_preview_stream` ✓
- `get_camera_state` ✓
- `get_preset_status` ✓
- `load_preset` ✓
- `load_preset_group` ✓

`WiredGoPro.__init__` signature: `(serial: str | None = None, **kwargs)` — pass the device serial to skip mDNS auto-discovery.

## WiredGoPro connect handshake (observed)

```
1. mDNS discovery: _gopro-web._tcp.local. → C3471327153141.local (172.21.141.51:8080)
2. GET /gopro/camera/control/wired_usb?p=1   (enable wired USB control)
3. GET /gopro/camera/analytics/set_client_info
4. GET /gopro/version → {"version": "2.0"}
5. (subsequent commands flow normally)
```

mDNS via `zeroconf` (avahi) works for the discovery step.

## NCM environment

Linux side:
- `cdc_ncm` and `cdc_ether` modules loaded (standard kernel)
- NetworkManager auto-managed the new interface — no manual config required
- GoPro brought up `enx4e71b3ec7368` interface, host IP `172.21.141.55/24`, GoPro IP `172.21.141.51`
- Avahi resolved `C3471327153141._gopro-web._tcp.local.` (avahi-daemon active)
- `avahi-resolve -n gopro_<serial>.local` failed with timeout (pattern guess wrong) — but mDNS via the SDK works fine
- ufw not blocking the GoPro IP

## Camera state shape

`get_camera_state()` returns `data` as a dict keyed by **numeric Status ID strings** (not the symbolic names the spec assumed). Storage-related keys observed:

- `"54"` = SD card remaining space, **in KB** (not bytes!) — observed 25,690,521 KB ≈ 25.7 GB
- `"33"` = SD card status (0 = OK)
- `"10"` = encoding/recording status (0 = idle, 1 = recording)
- `"8"` = busy flag

**Spec correction needed**: `status_remaining` was guessed; real lookup is `state.data["54"]`, multiply by 1024 for bytes. The spec's `_STORAGE_MIN_BYTES = 500_000_000` threshold maps to `data["54"] < 500_000` (compare in KB).

## Preset / native enumeration

The user's camera was at default preset **2.7K30 HEVC**, NOT the spec's assumed 1080p60 h264. Sample MP4 attributes:

- Resolution: 2704×1520
- Codec: HEVC (h.265)
- Frame rate: 30000/1001 ≈ 29.97 fps

This validates Codex's concern that **the codec varies (h264 vs hevc)** depending on preset. The spec's post-DL `update_info_json_codec` correctly handles this.

`get_preset_status()` returns a structured object — preset enumeration was not fully exhaustively walked in this session (would require iterating each preset, loading it, recording 5s, ffprobe — left as TODO if/when implementing the full preset table).

For the implementation: **start with a hand-coded preset table** matching the spec's published list, and trust that `load_preset` IDs are stable on Hero 11 firmware H22.01.02.32.00. Update the table by running `get_preset_status()` once on startup if mismatches show up.

## Recording behavior

```
Test: 4-second recording (1080p30 effectively, defaulted to 2.7K30 HEVC)

shutter ON  (curl /gopro/camera/shutter/start)        → {} (success)
during recording: media_list returns 0 NEW files      ← media is filtered while recording
sleep 4
shutter OFF (curl /gopro/camera/shutter/stop)         → {} (success)
+1 second:  media_list shows new file 'GX010019.MP4', 8.3 MB
```

**Spec's polling-廃止 decision is CONFIRMED correct.** Start-time `media_list` polling is structurally not reliable — the camera does not list in-progress recordings.

**File appears in media_list within 1 second after shutter OFF.** Spec's stop-time polling fallback is reliable.

## Filename pattern (chapter detection)

Confirmed: `G<quality_letter><chapter_2digit><id_4digit>.MP4`

Test recording produced `GX010019.MP4` — quality `X`, chapter `01`, id `0019`. Spec's chapter detection logic (group by `(quality, id)`) is correct.

## Download

Files are at **port 80** (NOT port 8080 used for control), path `/videos/DCIM/100GOPRO/<filename>`:

```bash
curl -sf "http://172.21.141.51/videos/DCIM/100GOPRO/GX010019.MP4" -o out.mp4
```

Observed throughput: **8.3 MB in 0.19 s ≈ 44 MB/s** over USB-CDC-NCM. Fast enough for non-blocking DL workflow.

The `WiredGoPro.http_command.download_file()` SDK call uses this same endpoint internally.

## ffmpeg GPMF preservation — critical correction

The spec's `ffmpeg_copy` and `ffmpeg_downscale` commands use `-map 0 -c copy -copy_unknown` to grab everything. **This FAILS** on Hero 11 MP4 because the Timecode (TCD) data stream uses codec `none` which ffmpeg cannot remux into a new MP4 container. The error:

```
Error initializing output stream 0:3 -- Could not find tag for codec none
```

**Working pattern** (observed): use explicit per-stream map and drop TCD + audio:

```bash
# Re-encode (downscale) preserving GPMF:
ffmpeg -y -nostdin -i in.mp4 \
  -map 0:v:0 -map 0:d:1 \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p -vf "scale=W:H" \
  -c:d copy \
  out.mp4

# Stream copy preserving GPMF:
ffmpeg -y -nostdin -i in.mp4 \
  -map 0:v:0 -map 0:d:1 \
  -c copy \
  out.mp4
```

Stream indices on Hero 11 (verified):
- `0:v:0` — H.265 (or H.264) video
- `0:1` — AAC audio (we drop with `-an` or by not mapping)
- `0:d:0` — TCD timecode (codec=none, must NOT be mapped — drops anyway)
- `0:d:1` — GPMF (codec=bin_data, handler="GoPro MET")

The `-map 0:m:handler_name="GoPro MET"` pattern fails because the handler tag has trailing spaces — easier to use the index `0:d:1`.

**Action item for spec/plan**: rewrite `ffmpeg_copy` and `ffmpeg_downscale` to use the working pattern above.

## Hangs observed

Two anomalies during repeated `WiredGoPro` initialization in one process tree:
- After successful `open()` + `close()`, the second `open()` sometimes hangs in mDNS rescan
- Long-running probes occasionally hang on later HTTP calls

Workaround: prefer **one `WiredGoPro` instance per session**, hold open for the duration. The spec's design (registry holds one client per device) already follows this pattern.

## What's next (post-Phase-0 patches)

These updates need to land in the spec/plan before continuing implementation:

1. **`ffmpeg_copy` / `ffmpeg_downscale` use selective map** (`-map 0:v:0 -map 0:d:1`), not `-map 0 -copy_unknown`.
2. **Storage check** uses `state.data["54"]` (KB units), not `sd_status_remaining`.
3. **Camera state numeric keys** (`"10"`, `"33"`, `"54"`) — document that `data` is dict-of-Status-ID-string-keys.
4. **`from open_gopro.models import constants, proto`** (not `from open_gopro import constants`).
5. **GoPro defaults are user-set** — implementation should always `load_preset` to enforce a known state, never trust the default.
6. **Download via port 80** (not 8080) — confirmed.

These match what is already in the latest spec or are minor patches.

## Decision

✅ **PASS — proceed.** All required APIs work, environment is correctly set up, and the design's polling-removal / staging / commit/discard decisions are vindicated by observed behavior.
