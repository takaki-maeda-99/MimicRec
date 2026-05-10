from mimicrec.errors import MimicRecError, PreviewDisabledError


def test_preview_disabled_error_is_mimicrec_error_subclass():
    err = PreviewDisabledError("preview disabled this session")
    assert isinstance(err, MimicRecError)
    assert str(err) == "preview disabled this session"
