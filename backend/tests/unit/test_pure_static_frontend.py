from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from app.services.static_frontend import resolve_frontend_path


class StaticPathTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "dist"
        self.root.mkdir()
        (self.root / "index.html").write_text("<!doctype html><title>Test only</title>")
        (self.root / "assets").mkdir()
        (self.root / "assets" / "app.js").write_text("// synthetic fixture")
        (self.root / "release.json").write_text('{"commit":"synthetic"}')

    def test_existing_assets_and_release_record_are_served(self):
        self.assertEqual(resolve_frontend_path(self.root, "assets/app.js"), self.root / "assets/app.js")
        self.assertEqual(resolve_frontend_path(self.root, "release.json"), self.root / "release.json")

    def test_root_and_extensionless_spa_routes(self):
        for path in ("", "flags", "flags/new-checkout"):
            with self.subTest(path=path):
                self.assertEqual(resolve_frontend_path(self.root, path), self.root / "index.html")

    def test_reserved_paths_and_missing_assets_never_return_index(self):
        for path in ("api", "api/v1/missing", "health", "health/unknown", "assets/missing", "assets/missing.js", "missing.css", "missing.json"):
            with self.subTest(path=path):
                with self.assertRaises(FileNotFoundError):
                    resolve_frontend_path(self.root, path)

    def test_traversal_hidden_paths_and_backslashes_are_rejected(self):
        for path in ("../secret", ".env", "assets/.hidden", "flags/../../secret", "assets\\app.js", "\x00"):
            with self.subTest(path=path):
                with self.assertRaises(FileNotFoundError):
                    resolve_frontend_path(self.root, path)

    def test_symlink_cannot_escape_build_directory(self):
        outside = Path(self.temporary.name) / "outside.js"
        outside.write_text("synthetic outside file")
        (self.root / "assets" / "link.js").symlink_to(outside)
        with self.assertRaises(FileNotFoundError):
            resolve_frontend_path(self.root, "assets/link.js")

    def test_index_symlink_cannot_escape_build_directory(self):
        outside = Path(self.temporary.name) / "private.html"
        outside.write_text("synthetic outside file")
        (self.root / "index.html").unlink()
        (self.root / "index.html").symlink_to(outside)
        with self.assertRaises(FileNotFoundError):
            resolve_frontend_path(self.root, "flags")

    def test_missing_index_is_not_a_fake_working_frontend(self):
        (self.root / "index.html").unlink()
        with self.assertRaises(FileNotFoundError):
            resolve_frontend_path(self.root, "")
