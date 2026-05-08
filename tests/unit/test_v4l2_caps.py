from unittest.mock import patch
from mimicrec.cameras.v4l2_caps import enumerate_capabilities, parse_v4l2_listfmts


SAMPLE_UVC = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture

\t[0]: 'MJPG' (Motion-JPEG, compressed)
\t\tSize: Discrete 1280x720
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t[1]: 'YUYV' (YUYV 4:2:2)
\t\tSize: Discrete 1280x720
\t\t\tInterval: Discrete 0.100s (10.000 fps)
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\t\tInterval: Discrete 0.067s (15.000 fps)
"""

SAMPLE_MPLANE = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture Multiplanar

\t[0]: 'NV12M' (Y/CbCr 4:2:0 (N-C))
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.033s (30.000 fps)
"""

SAMPLE_STEPWISE = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture

\t[0]: 'H264' (H.264, compressed)
\t\tSize: Stepwise 320x240 - 1280x720 with step 320/240
\t[1]: 'MJPG' (Motion-JPEG, compressed)
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
"""


def test_parse_uvc_camera():
    formats = parse_v4l2_listfmts(SAMPLE_UVC)
    assert len(formats) == 2

    mjpg = formats[0]
    assert mjpg.fourcc == "MJPG"
    assert "Motion-JPEG" in mjpg.description
    assert len(mjpg.sizes) == 2
    assert mjpg.sizes[0].width == 1280 and mjpg.sizes[0].height == 720
    assert mjpg.sizes[0].fps == [30]

    yuyv = formats[1]
    assert yuyv.fourcc == "YUYV"
    yuyv_640 = next(s for s in yuyv.sizes if s.width == 640)
    assert sorted(yuyv_640.fps, reverse=True) == [30, 15]


def test_skips_multiplane_format():
    formats = parse_v4l2_listfmts(SAMPLE_MPLANE)
    assert formats == []


def test_skips_stepwise_size():
    formats = parse_v4l2_listfmts(SAMPLE_STEPWISE)
    assert len(formats) == 1
    assert formats[0].fourcc == "MJPG"
    assert len(formats[0].sizes) == 1
    assert formats[0].sizes[0].width == 640


def test_enumerate_v4l2_ctl_missing_returns_empty():
    with patch("mimicrec.cameras.v4l2_caps.subprocess.run", side_effect=FileNotFoundError):
        assert enumerate_capabilities("/dev/video0") == []


def test_enumerate_nonzero_exit_returns_empty():
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "Cannot open device /dev/video99"
    with patch("mimicrec.cameras.v4l2_caps.subprocess.run", return_value=FakeResult()):
        assert enumerate_capabilities("/dev/video99") == []
