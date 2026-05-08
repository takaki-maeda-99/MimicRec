import numpy as np
from mimicrec.types import Frame


def test_preview_only_default_false():
    f = Frame(image=np.zeros((4, 4, 3), dtype=np.uint8))
    assert f.preview_only is False


def test_preview_only_settable():
    f = Frame(image=np.zeros((4, 4, 3), dtype=np.uint8), preview_only=True)
    assert f.preview_only is True
