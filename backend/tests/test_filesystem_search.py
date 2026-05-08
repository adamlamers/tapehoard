"""Tests for filesystem search endpoint."""

import pytest
from app.db import models


@pytest.fixture
def sample_files(db_session):
    """Create sample files for search testing."""
    files = [
        models.FilesystemState(
            file_path="/source_data/documents/test_file.txt",
            size=1024,
            mtime=1234567890,
            sha256_hash="abc123",
            is_ignored=False,
        ),
        models.FilesystemState(
            file_path="/source_data/documents/another_test.pdf",
            size=2048,
            mtime=1234567891,
            sha256_hash="def456",
            is_ignored=False,
        ),
        models.FilesystemState(
            file_path="/source_data/images/photo.jpg",
            size=4096,
            mtime=1234567892,
            sha256_hash="ghi789",
            is_ignored=False,
        ),
        models.FilesystemState(
            file_path="/source_data/documents/nested/deep/file.txt",
            size=512,
            mtime=1234567893,
            sha256_hash="jkl012",
            is_ignored=False,
        ),
        # File without hash (shouldn't appear in search)
        models.FilesystemState(
            file_path="/source_data/temp/temp.tmp",
            size=100,
            mtime=1234567894,
            sha256_hash=None,
            is_ignored=False,
        ),
        # Ignored file
        models.FilesystemState(
            file_path="/source_data/ignored/secret.txt",
            size=200,
            mtime=1234567895,
            sha256_hash="mno345",
            is_ignored=True,
        ),
    ]
    for f in files:
        db_session.add(f)
    db_session.commit()

    # Triggers automatically populate filesystem_fts, no manual insert needed

    return files


class TestFilesystemSearch:
    """Test suite for filesystem search endpoint."""

    def test_search_finds_files_by_name(self, client, db_session, sample_files):
        """Test that search finds files by filename."""
        response = client.get("/system/search?q=test")
        assert response.status_code == 200
        data = response.json()

        # Should find test_file.txt and another_test.pdf
        paths = [f["path"] for f in data]
        assert "/source_data/documents/test_file.txt" in paths
        assert "/source_data/documents/another_test.pdf" in paths

    def test_search_with_dot_in_query(self, client, db_session, sample_files):
        """Test that search handles dots in query (FTS5 syntax issue)."""
        response = client.get("/system/search?q=.txt")
        assert response.status_code == 200
        data = response.json()

        paths = [f["path"] for f in data]
        # Should find files containing .txt
        assert "/source_data/documents/test_file.txt" in paths
        assert "/source_data/documents/nested/deep/file.txt" in paths

    def test_search_with_full_extension(self, client, db_session, sample_files):
        """Test searching for file extension."""
        response = client.get("/system/search?q=pdf")
        assert response.status_code == 200
        data = response.json()

        paths = [f["path"] for f in data]
        assert "/source_data/documents/another_test.pdf" in paths

    def test_search_with_path_prefix(self, client, db_session, sample_files):
        """Test search with path filter."""
        response = client.get("/system/search?q=test&path=/source_data/documents")
        assert response.status_code == 200
        data = response.json()

        paths = [f["path"] for f in data]
        # Should only find files in documents directory
        assert "/source_data/documents/test_file.txt" in paths
        assert "/source_data/documents/another_test.pdf" in paths
        # Should NOT find images
        assert "/source_data/images/photo.jpg" not in paths

    def test_search_excludes_files_without_hash(self, client, db_session, sample_files):
        """Test that files without sha256_hash are excluded."""
        response = client.get("/system/search?q=temp")
        assert response.status_code == 200
        data = response.json()

        paths = [f["path"] for f in data]
        # temp.tmp has no hash, should not appear
        assert "/source_data/temp/temp.tmp" not in paths

    def test_search_excludes_ignored_files_by_default(
        self, client, db_session, sample_files
    ):
        """Test that ignored files are excluded by default."""
        response = client.get("/system/search?q=secret")
        assert response.status_code == 200
        data = response.json()

        paths = [f["path"] for f in data]
        # secret.txt is ignored, should not appear
        assert "/source_data/ignored/secret.txt" not in paths

    def test_search_includes_ignored_files_when_requested(
        self, client, db_session, sample_files
    ):
        """Test that ignored files can be included."""
        response = client.get("/system/search?q=secret&include_ignored=true")
        assert response.status_code == 200
        data = response.json()

        paths = [f["path"] for f in data]
        # With include_ignored=true, secret.txt should appear
        assert "/source_data/ignored/secret.txt" in paths

    def test_search_too_short_query(self, client, db_session, sample_files):
        """Test that queries < 3 chars return empty list."""
        response = client.get("/system/search?q=te")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_search_nested_path(self, client, db_session, sample_files):
        """Test searching finds files in nested directories."""
        response = client.get("/system/search?q=deep")
        assert response.status_code == 200
        data = response.json()

        paths = [f["path"] for f in data]
        assert "/source_data/documents/nested/deep/file.txt" in paths

    def test_search_case_insensitive(self, client, db_session, sample_files):
        """Test that search is case insensitive."""
        response = client.get("/system/search?q=TEST")
        assert response.status_code == 200
        data = response.json()

        paths = [f["path"] for f in data]
        # Should find test_file.txt (lowercase)
        assert "/source_data/documents/test_file.txt" in paths

    def test_search_with_special_characters(self, client, db_session, sample_files):
        """Test search handles special characters in query."""
        # Test with underscore
        response = client.get("/system/search?q=test_file")
        assert response.status_code == 200
        data = response.json()

        paths = [f["path"] for f in data]
        assert "/source_data/documents/test_file.txt" in paths

    def test_search_empty_query(self, client, db_session, sample_files):
        """Test that empty query returns empty list."""
        response = client.get("/system/search?q=")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_search_no_matches(self, client, db_session, sample_files):
        """Test that non-matching query returns empty list."""
        response = client.get("/system/search?q=nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data == []
