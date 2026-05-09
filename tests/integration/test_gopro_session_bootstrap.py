import pytest


@pytest.mark.asyncio
async def test_invalid_gopro_yaml_raises_http_400():
    """If a GoPro YAML specifies fps=25 (not supported), session start
    should return a 400 with a clear message — not a 500."""
    pytest.skip("Wire to API harness when ready (real test in Task 18)")
