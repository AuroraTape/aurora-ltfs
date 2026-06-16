def test_open_write_read(mounted_tape):
    p = mounted_tape / "hello.txt"
    p.write_text("hello world")
    assert p.read_text() == "hello world"
