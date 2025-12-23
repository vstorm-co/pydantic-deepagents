"""Tests for backend implementations."""

from pydantic_deep.backends.composite import CompositeBackend
from pydantic_deep.backends.filesystem import FilesystemBackend
from pydantic_deep.backends.state import StateBackend


class TestStateBackend:
    """Tests for StateBackend."""

    def test_write_and_read(self):
        """Test writing and reading a file."""
        backend = StateBackend()

        result = backend.write("/test.txt", "Hello, World!")
        assert result.error is None
        assert result.path == "/test.txt"

        content = backend.read("/test.txt")
        assert "Hello, World!" in content
        assert "1\t" in content  # Line number

    def test_write_multiline(self):
        """Test writing multiline content."""
        backend = StateBackend()

        content = "Line 1\nLine 2\nLine 3"
        backend.write("/multi.txt", content)

        result = backend.read("/multi.txt")
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_read_nonexistent(self):
        """Test reading a file that doesn't exist."""
        backend = StateBackend()

        result = backend.read("/nonexistent.txt")
        assert "Error:" in result
        assert "not found" in result

    def test_edit_file(self):
        """Test editing a file."""
        backend = StateBackend()

        backend.write("/test.txt", "Hello, World!")
        result = backend.edit("/test.txt", "World", "Universe")

        assert result.error is None
        assert result.occurrences == 1

        content = backend.read("/test.txt")
        assert "Universe" in content
        assert "World" not in content

    def test_edit_multiple_occurrences(self):
        """Test editing with multiple occurrences."""
        backend = StateBackend()

        backend.write("/test.txt", "foo bar foo baz foo")

        # Should fail without replace_all
        result = backend.edit("/test.txt", "foo", "qux")
        assert result.error is not None
        assert "3 times" in result.error

        # Should succeed with replace_all
        result = backend.edit("/test.txt", "foo", "qux", replace_all=True)
        assert result.error is None
        assert result.occurrences == 3

    def test_ls_info(self):
        """Test listing directory contents."""
        backend = StateBackend()

        backend.write("/dir/file1.txt", "content1")
        backend.write("/dir/file2.txt", "content2")
        backend.write("/dir/subdir/file3.txt", "content3")

        entries = backend.ls_info("/dir")
        names = [e["name"] for e in entries]

        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "subdir" in names

    def test_glob_info(self):
        """Test glob pattern matching."""
        backend = StateBackend()

        backend.write("/src/main.py", "# main")
        backend.write("/src/utils.py", "# utils")
        backend.write("/src/test.js", "// test")
        backend.write("/lib/helper.py", "# helper")

        # Find all Python files
        results = backend.glob_info("**/*.py")
        paths = [r["path"] for r in results]

        assert "/src/main.py" in paths
        assert "/src/utils.py" in paths
        assert "/lib/helper.py" in paths
        assert "/src/test.js" not in paths

    def test_grep_raw(self):
        """Test grep searching."""
        backend = StateBackend()

        backend.write("/test.py", "def hello():\n    print('Hello')")
        backend.write("/other.py", "def goodbye():\n    print('Goodbye')")

        results = backend.grep_raw("hello")
        assert isinstance(results, list)
        assert len(results) > 0
        assert any(r["path"] == "/test.py" for r in results)

    def test_path_validation(self):
        """Test path validation security."""
        backend = StateBackend()

        # Test .. traversal
        result = backend.write("/../etc/passwd", "hack")
        assert result.error is not None

        # Test ~ expansion
        result = backend.write("~/secret", "hack")
        assert result.error is not None

    def test_read_bytes(self):
        """Test reading raw bytes from files.

        Note: StateBackend stores content as text lines, so binary data
        with invalid UTF-8 sequences will be converted with errors='replace'.
        This is expected behavior for a text-based in-memory backend.
        """
        backend = StateBackend()

        # Write text content
        backend.write("/text.txt", "Hello, World!")
        data = backend._read_bytes("/text.txt")
        assert isinstance(data, bytes)
        assert data == b"Hello, World!"

        # Write valid UTF-8 bytes content (as text will round-trip correctly)
        backend.write("/valid_utf8.txt", "Hello 世界 🌍")
        data = backend._read_bytes("/valid_utf8.txt")
        assert isinstance(data, bytes)
        assert data == "Hello 世界 🌍".encode()

        # Test multiline content
        backend.write("/multi.txt", "Line 1\nLine 2\nLine 3")
        data = backend._read_bytes("/multi.txt")
        assert isinstance(data, bytes)
        assert data == b"Line 1\nLine 2\nLine 3"

        # Test non-existent file
        data = backend._read_bytes("/nonexistent.txt")
        assert isinstance(data, bytes)
        assert data == b""

        # Test empty file
        backend.write("/empty.txt", "")
        data = backend._read_bytes("/empty.txt")
        assert isinstance(data, bytes)
        assert data == b""

    def test_edge_case_filenames(self):
        """Test handling of edge case filenames with special characters."""
        backend = StateBackend()

        # Filename with spaces
        result = backend.write("/file with spaces.txt", "Content with spaces")
        assert result.error is None
        content = backend.read("/file with spaces.txt")
        assert "Content with spaces" in content

        # Filename with special characters
        result = backend.write("/file-name_test.123.txt", "Special chars")
        assert result.error is None
        content = backend.read("/file-name_test.123.txt")
        assert "Special chars" in content

        # Filename with unicode
        result = backend.write("/файл.txt", "Unicode filename")
        assert result.error is None
        content = backend.read("/файл.txt")
        assert "Unicode filename" in content

        # Filename with emoji
        result = backend.write("/file_🚀.txt", "Emoji filename")
        assert result.error is None
        content = backend.read("/file_🚀.txt")
        assert "Emoji filename" in content

        # Deep nested path
        result = backend.write("/very/deep/nested/path/to/file.txt", "Deep nested")
        assert result.error is None
        content = backend.read("/very/deep/nested/path/to/file.txt")
        assert "Deep nested" in content

        # Path with dots
        result = backend.write("/path/to/../file.txt", "Dots path")
        assert result.error is not None  # Should fail due to .. validation

        # Multiple extensions
        result = backend.write("/archive.tar.gz", "Archive content")
        assert result.error is None
        content = backend.read("/archive.tar.gz")
        assert "Archive content" in content

        # Filename with parentheses and brackets
        result = backend.write("/file (copy) [1].txt", "Brackets and parens")
        assert result.error is None
        content = backend.read("/file (copy) [1].txt")
        assert "Brackets and parens" in content

        # Filename with quotes (single and double)
        result = backend.write("/file's-name.txt", "Single quote")
        assert result.error is None
        content = backend.read("/file's-name.txt")
        assert "Single quote" in content


class TestFilesystemBackend:
    """Tests for FilesystemBackend."""

    def test_write_and_read(self, tmp_path):
        """Test writing and reading a file."""
        backend = FilesystemBackend(tmp_path)

        result = backend.write("/test.txt", "Hello, World!")
        assert result.error is None

        content = backend.read("/test.txt")
        assert "Hello, World!" in content

    def test_write_bytes(self, tmp_path):
        """Test writing bytes to a file."""
        backend = FilesystemBackend(tmp_path)

        result = backend.write("/binary.dat", b"\x80\x81\x82")
        assert result.error is None

        # Verify file was written as bytes
        full_path = tmp_path / "binary.dat"
        assert full_path.exists()
        assert full_path.read_bytes() == b"\x80\x81\x82"

    def test_virtual_mode(self, tmp_path):
        """Test virtual_mode creates directory."""
        new_dir = tmp_path / "new_virtual_dir"
        assert not new_dir.exists()

        _ = FilesystemBackend(new_dir, virtual_mode=True)
        assert new_dir.exists()

    def test_edit_file(self, tmp_path):
        """Test editing a file."""
        backend = FilesystemBackend(tmp_path)

        backend.write("/test.txt", "Hello, World!")
        result = backend.edit("/test.txt", "World", "Universe")

        assert result.error is None

        content = backend.read("/test.txt")
        assert "Universe" in content

    def test_glob_info(self, tmp_path):
        """Test glob pattern matching."""
        backend = FilesystemBackend(tmp_path)

        backend.write("/src/main.py", "# main")
        backend.write("/src/utils.py", "# utils")

        results = backend.glob_info("**/*.py")
        assert len(results) == 2

    def test_read_bytes(self, tmp_path):
        """Test reading raw bytes from files."""
        backend = FilesystemBackend(tmp_path)

        # Write text content
        backend.write("/text.txt", "Hello, World!")
        data = backend._read_bytes("/text.txt")
        assert isinstance(data, bytes)
        assert data == b"Hello, World!"

        # Write binary content
        backend.write("/binary.dat", b"\x00\x01\x02\xff\xfe")
        data = backend._read_bytes("/binary.dat")
        assert isinstance(data, bytes)
        assert data == b"\x00\x01\x02\xff\xfe"

        # Test multiline content
        backend.write("/multi.txt", "Line 1\nLine 2\nLine 3")
        data = backend._read_bytes("/multi.txt")
        assert isinstance(data, bytes)
        assert data == b"Line 1\nLine 2\nLine 3"

        # Test non-existent file
        data = backend._read_bytes("/nonexistent.txt")
        assert isinstance(data, bytes)
        assert data == b""

        # Test UTF-8 content
        backend.write("/unicode.txt", "Hello 世界 🌍")
        data = backend._read_bytes("/unicode.txt")
        assert isinstance(data, bytes)
        assert data == "Hello 世界 🌍".encode()

        # Test empty file
        backend.write("/empty.txt", "")
        data = backend._read_bytes("/empty.txt")
        assert isinstance(data, bytes)
        assert data == b""

    def test_edge_case_filenames(self, tmp_path):
        """Test handling of edge case filenames with special characters."""
        backend = FilesystemBackend(tmp_path)

        # Filename with spaces
        result = backend.write("/file with spaces.txt", "Content with spaces")
        assert result.error is None
        content = backend.read("/file with spaces.txt")
        assert "Content with spaces" in content
        # Verify file actually exists on filesystem
        assert (tmp_path / "file with spaces.txt").exists()

        # Filename with special characters
        result = backend.write("/file-name_test.123.txt", "Special chars")
        assert result.error is None
        content = backend.read("/file-name_test.123.txt")
        assert "Special chars" in content

        # Filename with unicode
        result = backend.write("/файл.txt", "Unicode filename")
        assert result.error is None
        content = backend.read("/файл.txt")
        assert "Unicode filename" in content
        assert (tmp_path / "файл.txt").exists()

        # Filename with emoji
        result = backend.write("/file_🚀.txt", "Emoji filename")
        assert result.error is None
        content = backend.read("/file_🚀.txt")
        assert "Emoji filename" in content

        # Deep nested path
        result = backend.write("/very/deep/nested/path/to/file.txt", "Deep nested")
        assert result.error is None
        content = backend.read("/very/deep/nested/path/to/file.txt")
        assert "Deep nested" in content
        assert (tmp_path / "very" / "deep" / "nested" / "path" / "to" / "file.txt").exists()

        # Path with dots (should fail validation)
        result = backend.write("/path/to/../file.txt", "Dots path")
        assert result.error is not None  # Should fail due to .. validation

        # Multiple extensions
        result = backend.write("/archive.tar.gz", "Archive content")
        assert result.error is None
        content = backend.read("/archive.tar.gz")
        assert "Archive content" in content

        # Filename with parentheses and brackets
        result = backend.write("/file (copy) [1].txt", "Brackets and parens")
        assert result.error is None
        content = backend.read("/file (copy) [1].txt")
        assert "Brackets and parens" in content
        assert (tmp_path / "file (copy) [1].txt").exists()

        # Filename with single quote
        result = backend.write("/file's-name.txt", "Single quote")
        assert result.error is None
        content = backend.read("/file's-name.txt")
        assert "Single quote" in content

        # Test editing file with spaces
        edit_result = backend.edit("/file with spaces.txt", "Content", "Modified")
        assert edit_result.error is None
        content = backend.read("/file with spaces.txt")
        assert "Modified with spaces" in content

        # Binary file with special name
        result = backend.write("/data (binary) [v2].bin", b"\x00\x01\x02\x03")
        assert result.error is None
        data = backend._read_bytes("/data (binary) [v2].bin")
        assert data == b"\x00\x01\x02\x03"


class TestCompositeBackend:
    """Tests for CompositeBackend."""

    def test_routing(self):
        """Test that operations are routed to correct backend."""
        memory_backend = StateBackend()
        temp_backend = StateBackend()

        composite = CompositeBackend(
            default=memory_backend,
            routes={"/temp/": temp_backend},
        )

        # Write to default backend
        composite.write("/data.txt", "default data")
        assert "/data.txt" in memory_backend.files
        assert "/data.txt" not in temp_backend.files

        # Write to temp backend
        composite.write("/temp/cache.txt", "temp data")
        assert "/temp/cache.txt" in temp_backend.files
        assert "/temp/cache.txt" not in memory_backend.files

    def test_aggregated_ls(self):
        """Test that root ls aggregates from all backends."""
        backend1 = StateBackend()
        backend2 = StateBackend()

        backend1.write("/file1.txt", "content1")
        backend2.write("/special/file2.txt", "content2")

        composite = CompositeBackend(
            default=backend1,
            routes={"/special/": backend2},
        )

        entries = composite.ls_info("/")
        names = [e["name"] for e in entries]

        assert "file1.txt" in names
        assert "special" in names  # Virtual directory for route

    def test_read_bytes(self):
        """Test reading raw bytes through composite backend.

        Note: Using StateBackend instances which store text, so binary
        data will be converted. This tests routing, not binary handling.
        """
        backend1 = StateBackend()
        backend2 = StateBackend()

        composite = CompositeBackend(
            default=backend1,
            routes={"/special/": backend2},
        )

        # Write to default backend
        composite.write("/default.txt", "default content")
        data = composite._read_bytes("/default.txt")
        assert isinstance(data, bytes)
        assert data == b"default content"

        # Write to routed backend
        composite.write("/special/routed.txt", "routed content")
        data = composite._read_bytes("/special/routed.txt")
        assert isinstance(data, bytes)
        assert data == b"routed content"

        # Write UTF-8 text to routed backend
        composite.write("/special/unicode.txt", "Hello 世界")
        data = composite._read_bytes("/special/unicode.txt")
        assert isinstance(data, bytes)
        assert data == "Hello 世界".encode()

        # Test non-existent file
        data = composite._read_bytes("/nonexistent.txt")
        assert isinstance(data, bytes)
        assert data == b""

    def test_edge_case_filenames_routing(self, tmp_path):
        """Test routing with edge case filenames across different backends."""
        # Use FilesystemBackend for better binary handling
        fs_backend = FilesystemBackend(tmp_path / "default", virtual_mode=True)
        special_backend = FilesystemBackend(tmp_path / "special", virtual_mode=True)

        composite = CompositeBackend(
            default=fs_backend,
            routes={"/special/": special_backend},
        )

        # File with spaces in default backend
        result = composite.write("/file with spaces.txt", "default backend")
        assert result.error is None
        content = composite.read("/file with spaces.txt")
        assert "default backend" in content

        # File with spaces in routed backend
        result = composite.write("/special/file with spaces.txt", "routed backend")
        assert result.error is None
        content = composite.read("/special/file with spaces.txt")
        assert "routed backend" in content

        # Unicode filenames in different backends
        result = composite.write("/файл.txt", "default unicode")
        assert result.error is None
        result = composite.write("/special/文件.txt", "routed unicode")
        assert result.error is None

        # Emoji filenames
        result = composite.write("/emoji_😀.txt", "default emoji")
        assert result.error is None
        result = composite.write("/special/emoji_🚀.txt", "routed emoji")
        assert result.error is None

        # Complex filenames with special chars
        result = composite.write("/report (final) [v2.1].txt", "default complex")
        assert result.error is None
        result = composite.write("/special/data [backup] (2024).txt", "routed complex")
        assert result.error is None

        # Verify routing is correct
        assert "default complex" in composite.read("/report (final) [v2.1].txt")
        assert "routed complex" in composite.read("/special/data [backup] (2024).txt")

        # Deep nested paths with special chars
        result = composite.write("/deep/path with spaces/file.txt", "default nested")
        assert result.error is None
        result = composite.write("/special/deep/path (v2)/file's.txt", "routed nested")
        assert result.error is None

        # Verify actual filesystem storage (paths include full virtual paths)
        assert (tmp_path / "default" / "file with spaces.txt").exists()
        # Routed backend stores with full path including /special/ prefix
        assert (tmp_path / "special" / "special" / "file with spaces.txt").exists()
        assert (tmp_path / "default" / "report (final) [v2.1].txt").exists()

        # Test editing files with special names across backends
        edit_result = composite.edit("/file with spaces.txt", "default", "modified")
        assert edit_result.error is None
        assert "modified backend" in composite.read("/file with spaces.txt")

        edit_result = composite.edit("/special/file with spaces.txt", "routed", "updated")
        assert edit_result.error is None
        assert "updated backend" in composite.read("/special/file with spaces.txt")

        # Binary files with special names in different backends
        result = composite.write("/binary (data) [v1].bin", b"\x00\x01\x02")
        assert result.error is None
        result = composite.write("/special/binary (cache) [v2].bin", b"\xff\xfe\xfd")
        assert result.error is None

        # Verify binary data is preserved
        assert composite._read_bytes("/binary (data) [v1].bin") == b"\x00\x01\x02"
        assert composite._read_bytes("/special/binary (cache) [v2].bin") == b"\xff\xfe\xfd"
