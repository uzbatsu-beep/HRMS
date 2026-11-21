"""Unit tests for the repository-local Markdown link validator."""

import unittest
from pathlib import Path

from scripts.check_docs import ROOT, links_from_markdown, relative_target


class TestMarkdownLinks(unittest.TestCase):
    def test_ordinary_markdown_and_external(self) -> None:
        text = ("[local](docs/DEVELOPMENT.md#check)\n"
                "[external](https://github.com/uzbatsu-beep/HRMS)\n"
                "[anchor](#section)\n")
        self.assertEqual(len(links_from_markdown(text)), 3)
        self.assertEqual(
            relative_target(ROOT / "README.md", "docs/DEVELOPMENT.md#check"),
            ROOT / "docs" / "DEVELOPMENT.md",
        )
        self.assertIsNone(relative_target(ROOT / "README.md", "#section"))
        self.assertIsNone(relative_target(ROOT / "README.md", "https://github.com"))

    def test_fenced_code_excluded(self) -> None:
        code = ("[a](README.md)\n"
                "~~~python\n"
                "[ignored](does_not_exist.md)\n"
                "~~~\n"
                "[b](LICENSE)\n")
        self.assertEqual(
            links_from_markdown(code),
            ["README.md", "LICENSE"],
        )

    def test_rejects_out_of_repository(self) -> None:
        escaped = relative_target(ROOT / "README.md", "../outside.md")
        self.assertIsNotNone(escaped)
        assert escaped is not None
        self.assertFalse(escaped.is_relative_to(ROOT))

    def test_percent_encoding_and_directory(self) -> None:
        self.assertEqual(
            relative_target(ROOT / "docs" / "README.md", "../docs/adr/"),
            ROOT / "docs" / "adr",
        )
        self.assertEqual(
            relative_target(ROOT / "docs" / "README.md", "%44EVELOPMENT.md"),
            ROOT / "docs" / "DEVELOPMENT.md",
        )


if __name__ == "__main__":
    unittest.main()
