from common.helpers import full_sync, get_xattr, get_xattr_int


def test_full_sync_increments_generation(mounted_tape):
    g0 = get_xattr_int(mounted_tape, "ltfs.indexGeneration")
    loc0 = get_xattr(mounted_tape, "ltfs.indexLocation")

    (mounted_tape / "fs_sync.txt").write_text("payload")

    full_sync(mounted_tape, reason="test_full_sync_increments_generation")

    assert get_xattr_int(mounted_tape, "ltfs.indexGeneration") == g0 + 1
    assert get_xattr(mounted_tape, "ltfs.indexLocation") != loc0
