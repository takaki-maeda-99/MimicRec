import shutil
from pathlib import Path

import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.types import GoProSpec


@pytest.mark.asyncio
async def test_connect_disconnect_idempotent():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect(); await d.connect()
    await d.disconnect(); await d.disconnect()


@pytest.mark.asyncio
async def test_shutter_cycle_creates_one_file_by_default():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    before = await d.media_list()
    await d.shutter_on(); await d.shutter_off()
    after = await d.media_list()
    assert len(after) == len(before) + 1


@pytest.mark.asyncio
async def test_chapter_split_creates_multiple_files():
    d = MockGoProDevice(name="g1", usb_serial="S1", chapters_per_episode=3)
    await d.connect()
    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    assert len(files) == 3
    # all share same id (last 4 digits), differ in chapter (middle 2 digits)
    names = [f.filename for f in files]
    ids = {n[-8:-4] for n in names}     # last 4 digits before .MP4
    chapters = [n[2:4] for n in names]
    assert len(ids) == 1
    assert sorted(chapters) == ["01", "02", "03"]


def test_get_spec_returns_yaml_target():
    d = MockGoProDevice(name="g1", usb_serial="S1", width=1280, height=720, fps=30)
    spec = d.get_spec()
    assert spec == GoProSpec(name="g1", width=1280, height=720, fps=30, codec="libx264")


@pytest.mark.asyncio
async def test_unsupported_fps_raises():
    with pytest.raises((ValueError, Exception)):
        MockGoProDevice(name="g1", usb_serial="S1", fps=25)


@pytest.mark.asyncio
async def test_download_copies_fixture(tmp_path):
    fixture = tmp_path / "fixture.mp4"
    fixture.write_bytes(b"\x00" * 4096)
    # also accept str path (Hydra would pass str)
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=str(fixture))
    await d.connect()
    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    dst = tmp_path / "out.mp4"
    await d.download_file(files[-1].filename, dst)
    assert dst.stat().st_size == 4096


@pytest.mark.asyncio
async def test_disable_blocks_subsequent_calls():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    d.disable("test")
    assert d.is_disabled
    await d.shutter_on(); await d.shutter_off()  # no-op
