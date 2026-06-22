import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from changelog_ai.osc_wrapper import (
    is_changelog_file,
    extract_latest_changelog,
    clean_obs_diff,
    parse_multi_file_diff,
    expand_macros,
    parse_github_owner_repo,
    get_source_archive_filename,
    clean_spec_diff,
    render_template,
    truncate_to_max_length,
    has_real_content,
)


class TestOSCWrapperRefactored(unittest.TestCase):
    def test_is_changelog_file(self):
        self.assertTrue(is_changelog_file("CHANGELOG.md"))
        self.assertTrue(is_changelog_file("changelog"))
        self.assertTrue(is_changelog_file("news.txt"))
        self.assertTrue(is_changelog_file("changes"))
        self.assertFalse(is_changelog_file("main.py"))
        self.assertFalse(is_changelog_file("setup.cfg"))

    def test_extract_latest_changelog(self):
        content = """-------------------------------------------------------------------
Mon Jun 22 12:00:00 UTC 2026 - developer@example.com

- Fixed a bug in the parser
- Added new features

-------------------------------------------------------------------
Tue May 20 10:00:00 UTC 2026 - older@example.com

- Older release notes
"""
        latest = extract_latest_changelog(content)
        self.assertEqual(latest, "- Fixed a bug in the parser\n- Added new features")

        # Fallback if no marker is found
        simple_content = "Just some random notes"
        self.assertEqual(extract_latest_changelog(simple_content), "Just some random notes")

    def test_clean_obs_diff(self):
        diff = """Index: main.py
===================================================================
--- main.py
+++ main.py
@@ -10,3 +10,4 @@
-------------------------------------------------------------------
Mon Jun 22 12:00:00 UTC 2026 - developer@example.com
-old line
+new line
"""
        cleaned = clean_obs_diff(diff)
        expected = """Index: main.py
===================================================================
--- main.py
+++ main.py
-old line
+new line"""
        self.assertEqual(cleaned, expected)

    def test_parse_multi_file_diff(self):
        multi_diff = """Index: package.spec
===================================================================
--- package.spec
+++ package.spec
@@ -1,3 +1,3 @@
-Version: 1.0.0
+Version: 1.1.0
Index: _service
===================================================================
--- _service
+++ _service
@@ -2,2 +2,2 @@
-<param name="revision">v1.0.0</param>
+<param name="revision">v1.1.0</param>
"""
        file_diffs = parse_multi_file_diff(multi_diff)
        self.assertIn("package.spec", file_diffs)
        self.assertIn("_service", file_diffs)
        self.assertIn("Version: 1.1.0", file_diffs["package.spec"])
        self.assertIn("<param name=\"revision\">v1.1.0</param>", file_diffs["_service"])

    def test_expand_macros(self):
        template_str = "%{name}-%{version}.tar.gz"
        expanded = expand_macros(template_str, "my-pkg", "1.2.3")
        self.assertEqual(expanded, "my-pkg-1.2.3.tar.gz")

        expanded_simple = expand_macros("%name-%version", "my-pkg", "1.2.3")
        self.assertEqual(expanded_simple, "my-pkg-1.2.3")

    def test_parse_github_owner_repo(self):
        url1 = "https://github.com/google/gemini-cli.git"
        owner1, repo1 = parse_github_owner_repo(url1)
        self.assertEqual(owner1, "google")
        self.assertEqual(repo1, "gemini-cli")

        url2 = "git@github.com:mslacken/changelog-gen.git#fragment"
        owner2, repo2 = parse_github_owner_repo(url2)
        self.assertEqual(owner2, "mslacken")
        self.assertEqual(repo2, "changelog-gen")

        url3 = "https://github.com/foo/bar?query=1"
        owner3, repo3 = parse_github_owner_repo(url3)
        self.assertEqual(owner3, "foo")
        self.assertEqual(repo3, "bar")

    def test_get_source_archive_filename(self):
        source = "https://github.com/foo/bar/archive/v%{version}.tar.gz#./%{name}-%{version}.tar.gz"
        filename = get_source_archive_filename(source, "bar", "1.2.3")
        self.assertEqual(filename, "bar-1.2.3.tar.gz")

    def test_clean_spec_diff(self):
        spec_diff = """-Version: 1.0.0
+Version: 1.1.0
-# Copyright (c) 2026 SUSE LLC
+# Copyright (c) 2026 SUSE LLC and contributors
-BuildRequires:  python3-devel
+BuildRequires:  python311-devel
"""
        cleaned = clean_spec_diff(spec_diff)
        # Should exclude version lines and copyright lines, but keep other modified lines
        self.assertEqual(cleaned, "-BuildRequires:  python3-devel\n+BuildRequires:  python311-devel")

    def test_render_template(self):
        item = {
            "package": "test-pkg",
            "old_version": "1.0.0",
            "new_version": "1.1.0",
            "added_files": ["new_file.py"],
            "removed_files": ["old_file.py"],
            "_service": "service diff content",
            "spec_diff": "spec diff content",
        }
        rendered = render_template(item)
        expected_lines = [
            "create structured changelog for package test-pkg from 1.0.0 to 1.1.0:",
            "new files: ['new_file.py']",
            "removed files: ['old_file.py']",
            "changes in _service:",
            "service diff content",
            "changes in spec file:",
            "spec diff content",
        ]
        for line in expected_lines:
            self.assertIn(line, rendered)

    def test_truncate_to_max_length(self):
        class MockTokenizer:
            def __init__(self):
                self.words = []

            def encode(self, text):
                class Encoding:
                    def __init__(self, ids):
                        self.ids = ids
                self.words = text.split()
                return Encoding(list(range(len(self.words))))

            def decode(self, ids):
                return " ".join([self.words[i] for i in ids if i < len(self.words)])

        item = {
            "package": "test-pkg",
            "spec_diff": "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10",
        }
        tokenizer = MockTokenizer()
        
        # Limit to extremely small word count to trigger truncation of spec_diff
        truncated = truncate_to_max_length(item, tokenizer, max_length=10)
        # Verify it has been truncated
        self.assertIn("test-pkg", truncated)
        self.assertTrue(len(truncated.split()) <= 10)

    def test_has_real_content(self):
        # Empty/Blank content should be False
        self.assertFalse(has_real_content(""))
        self.assertFalse(has_real_content("   \n   "))
        
        # Only header lines (separator + date header) should be False
        header_only = """-------------------------------------------------------------------
Mon Jun 22 12:00:00 UTC 2026 - developer@example.com
"""
        self.assertFalse(has_real_content(header_only))
        
        # Header + actual entries should be True
        valid_content = """-------------------------------------------------------------------
Mon Jun 22 12:00:00 UTC 2026 - developer@example.com

- Fixed bug in the tokenizer
- Added some options
"""
        self.assertTrue(has_real_content(valid_content))


if __name__ == "__main__":
    unittest.main()
