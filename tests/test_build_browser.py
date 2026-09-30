import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_browser


def runtime_archive():
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name in build_browser.RUNTIME_FILES:
            data = b"Synthetic runtime fixture"
            entry = tarfile.TarInfo(f"package/{name}")
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    return output.getvalue()


class BrowserBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "dist"
        self.cache = Path(self.temp.name) / "cache"

    def test_contaminated_output_is_rejected_before_writing_or_downloading(self):
        self.output.mkdir()
        sentinel = self.output / "private-backup.json"
        sentinel.write_text("Synthetic private data", encoding="utf-8")
        index = self.output / "index.html"
        index.write_text("Previous generated page", encoding="utf-8")
        with patch.object(build_browser, "download_runtime", return_value=runtime_archive()) as download:
            with self.assertRaisesRegex(ValueError, "unallowlisted"):
                build_browser.build(self.output, self.cache)
        download.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "Synthetic private data")
        self.assertEqual(index.read_text(encoding="utf-8"), "Previous generated page")

    def test_clean_rebuild_contains_only_the_allowed_files(self):
        with patch.object(build_browser, "download_runtime", return_value=runtime_archive()):
            build_browser.build(self.output, self.cache)
            build_browser.build(self.output, self.cache)
        expected = set(build_browser.WEB_FILES) | {"roomies-python.zip"}
        expected |= {f"vendor/pyodide/{name}" for name in build_browser.RUNTIME_FILES}
        expected |= {f"vendor/pyodide/{name}" for name in ("PYODIDE-LICENSE", "PYTHON-LICENSE", "NOTICE.txt")}
        actual = {entry.relative_to(self.output).as_posix() for entry in self.output.rglob("*") if entry.is_file()}
        self.assertEqual(actual, expected)
        with zipfile.ZipFile(self.output / "roomies-python.zip") as bundle:
            self.assertEqual(set(bundle.namelist()), {f"roommate/{name}" for name in build_browser.PYTHON_FILES})

    def test_nested_private_files_also_block_rebuild(self):
        runtime = self.output / "vendor" / "pyodide"
        runtime.mkdir(parents=True)
        sentinel = runtime / "secret.env"
        sentinel.write_text("Synthetic secret", encoding="utf-8")
        with patch.object(build_browser, "download_runtime") as download:
            with self.assertRaisesRegex(ValueError, "unallowlisted"):
                build_browser.build(self.output, self.cache)
        download.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "Synthetic secret")
