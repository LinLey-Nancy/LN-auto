import importlib.metadata
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from window_auto import __version__
from window_auto.update import (
    ReleaseAsset,
    UpdateCheckError,
    is_newer,
    parse_release,
    parse_version,
    select_installer_asset,
)
from window_auto.version import current_version


class ParseVersionTests(unittest.TestCase):
    def test_versions_with_and_without_prefix(self) -> None:
        self.assertEqual(parse_version("v0.1.2"), (0, 1, 2))
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("0.2"), (0, 2))
        self.assertEqual(parse_version(" v1.0 "), (1, 0))

    def test_invalid_versions_are_rejected(self) -> None:
        for text in ("", "abc", "v", "1.x"):
            with self.assertRaises(UpdateCheckError, msg=text):
                parse_version(text)


class IsNewerTests(unittest.TestCase):
    def test_basic_comparison(self) -> None:
        self.assertTrue(is_newer("v0.2.0", "0.1.9"))
        self.assertTrue(is_newer("0.1.2", "0.1.1"))
        self.assertFalse(is_newer("0.1.1", "0.1.1"))
        self.assertFalse(is_newer("v0.1.0", "0.1.1"))

    def test_missing_segments_count_as_zero(self) -> None:
        self.assertFalse(is_newer("1.0", "1.0.0"))
        self.assertTrue(is_newer("1.0.1", "1.0"))


class SelectInstallerAssetTests(unittest.TestCase):
    def test_setup_exe_is_preferred(self) -> None:
        assets = [
            {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"},
            {"name": "LN-auto-v0.2.0-Setup.exe", "browser_download_url": "https://x/setup.exe", "size": 10},
            {"name": "portable.exe", "browser_download_url": "https://x/portable.exe"},
        ]

        asset = select_installer_asset(assets)

        self.assertIsNotNone(asset)
        self.assertEqual(asset.name, "LN-auto-v0.2.0-Setup.exe")
        self.assertEqual(asset.size, 10)

    def test_any_exe_is_accepted_when_no_setup_exists(self) -> None:
        assets = [
            {"name": "portable.exe", "browser_download_url": "https://x/p.exe"},
        ]

        asset = select_installer_asset(assets)

        self.assertIsNotNone(asset)
        self.assertEqual(asset.download_url, "https://x/p.exe")

    def test_no_exe_means_no_asset(self) -> None:
        self.assertIsNone(
            select_installer_asset(
                [{"name": "source.zip", "browser_download_url": "https://x/z.zip"}]
            )
        )
        self.assertIsNone(select_installer_asset([]))
        self.assertIsNone(select_installer_asset([{"name": 1}]))


class ParseReleaseTests(unittest.TestCase):
    def test_full_payload(self) -> None:
        release = parse_release(
            {
                "tag_name": "v0.2.0",
                "name": "LN-auto v0.2.0",
                "body": "若干改进",
                "html_url": "https://github.com/LinLey-Nancy/LN-auto/releases/tag/v0.2.0",
                "published_at": "2026-10-01T08:00:00Z",
                "assets": [
                    {
                        "name": "LN-auto-v0.2.0-Setup.exe",
                        "browser_download_url": "https://x/setup.exe",
                        "size": 100,
                    }
                ],
            }
        )

        self.assertEqual(release.version, "0.2.0")
        self.assertEqual(release.name, "LN-auto v0.2.0")
        self.assertEqual(release.notes, "若干改进")
        self.assertEqual(release.published_at, "2026-10-01T08:00:00Z")
        self.assertIsNotNone(release.asset)
        self.assertEqual(release.asset.download_url, "https://x/setup.exe")

    def test_missing_tag_is_rejected(self) -> None:
        with self.assertRaises(UpdateCheckError):
            parse_release({"name": "oops"})
        with self.assertRaises(UpdateCheckError):
            parse_release({"tag_name": "not-a-version"})

    def test_release_without_assets_still_parses(self) -> None:
        release = parse_release({"tag_name": "v1.0.0"})

        self.assertEqual(release.version, "1.0.0")
        self.assertIsNone(release.asset)
        self.assertEqual(release.name, "v1.0.0")


class CurrentVersionTests(unittest.TestCase):
    def test_version_file_takes_precedence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "version.txt").write_text("9.9.9\n", encoding="utf-8")

            with patch("window_auto.version.project_root", return_value=root):
                self.assertEqual(current_version(), "9.9.9")

    def test_installed_metadata_is_used_without_version_file(self) -> None:
        with TemporaryDirectory() as directory:
            with patch("window_auto.version.project_root", return_value=Path(directory)):
                self.assertEqual(
                    current_version(), importlib.metadata.version("LN-auto")
                )

    def test_constant_is_the_last_resort(self) -> None:
        with TemporaryDirectory() as directory:
            with (
                patch("window_auto.version.project_root", return_value=Path(directory)),
                patch(
                    "importlib.metadata.version",
                    side_effect=importlib.metadata.PackageNotFoundError,
                ),
            ):
                self.assertEqual(current_version(), __version__)


if __name__ == "__main__":
    unittest.main()
