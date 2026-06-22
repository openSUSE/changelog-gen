"""OSC wrapper for AI changelog generation."""

import argparse
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .cli import create_changelog_entry, get_changes, open_editor
from .model import ChangelogGenerator


def parse_args():
    """Parse command-line arguments for osc wrapper."""
    parser = argparse.ArgumentParser(
        description="AI-powered changelog generator for osc packages",
        epilog="Similar to 'osc vc' but uses AI to generate changelog entries",
    )

    parser.add_argument(
        "--model-size",
        choices=["small", "base", "large"],
        default="large",
        help="Model size: small/base/large (default: large)",
    )

    parser.add_argument(
        "--quantization",
        choices=["float32", "float16", "int8_float16", "int8"],
        default="int8",
        help="Quantization: float32/float16/int8_float16/int8 (default: int8)",
    )

    parser.add_argument(
        "--model-path",
        help="Path to T5 model directory",
    )

    parser.add_argument(
        "--device",
        choices=["cpu", "cuda"],
        default="cpu",
        help="Device: cpu/cuda (default: cpu)",
    )

    return parser.parse_args()


def is_changelog_file(filename: str) -> bool:
    """Check if a filename looks like a changelog, changes, or news file."""
    base = Path(filename).name.lower()
    prefixes = ["changelog", "changlog", "changes", "news"]
    return any(base.startswith(p) for p in prefixes)


def extract_latest_changelog(content: str) -> str:
    """Extract the latest entry from a .changes or changelog file using OBS style markers."""
    marker = "-------------------------------------------------------------------"
    if marker not in content:
        return content.strip()

    parts = content.split(marker)
    for part in parts:
        trimmed = part.strip()
        if not trimmed:
            continue
        # Skip the first line which is usually the metadata (date, author)
        lines = trimmed.split("\n", 1)
        if len(lines) > 1:
            return lines[1].strip()
    return ""


def clean_obs_diff(diff_text: str) -> str:
    """Removes the OBS limiter line, author/date line, diff hunk headers, and empty lines from diffs."""
    if not diff_text:
        return ""

    marker = "-------------------------------------------------------------------"
    lines = diff_text.splitlines()
    new_lines = []
    skip_next = False

    for line in lines:
        if marker in line:
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        if line.startswith("@@") or not line.strip():
            continue
        new_lines.append(line)

    return "\n".join(new_lines).strip()


def parse_multi_file_diff(diff_text: str) -> Dict[str, str]:
    """Parses a unified diff containing multiple files and splits it by filename."""
    file_diffs = {}
    current_file = None
    current_lines = []

    for line in diff_text.splitlines():
        # Check for osc diff file header (Index: filename)
        if line.startswith("Index: "):
            if current_file and current_lines:
                file_diffs[current_file] = "\n".join(current_lines)
            current_file = Path(line[7:].strip()).name
            current_lines = []
            continue
        # Check for git diff file header (diff --git b/file)
        elif line.startswith("diff --git "):
            if current_file and current_lines:
                file_diffs[current_file] = "\n".join(current_lines)
            parts = line.split()
            if len(parts) >= 4:
                b_path = parts[3]
                if b_path.startswith("b/"):
                    b_path = b_path[2:]
                current_file = Path(b_path).name
            else:
                current_file = None
            current_lines = []
            continue

        if current_file is not None:
            current_lines.append(line)

    if current_file and current_lines:
        file_diffs[current_file] = "\n".join(current_lines)

    return file_diffs


def get_added_removed_files() -> Tuple[List[str], List[str]]:
    """Determine added and removed files in the package via osc or git."""
    added = []
    removed = []

    # Try osc status first
    try:
        result = subprocess.run(
            ["osc", "status"], capture_output=True, text=True, check=True
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                status, filepath = parts
                filepath = Path(filepath).name
                if status == "A":
                    added.append(filepath)
                elif status in ("D", "R", "!"):
                    removed.append(filepath)
        return added, removed
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Fallback to git status --porcelain
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        )
        for line in result.stdout.splitlines():
            if not line:
                continue
            status = line[:2]
            filepath = line[3:].strip()
            if " -> " in filepath:
                filepath = filepath.split(" -> ")[-1]
            filepath = Path(filepath).name
            if "A" in status or "?" in status:
                added.append(filepath)
            elif "D" in status:
                removed.append(filepath)
        return added, removed
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return added, removed


def parse_spec_file() -> Dict[str, str]:
    """Finds the .spec file in the current directory and parses Name, Version, Source, URL."""
    spec_files = list(Path(".").glob("*.spec"))
    if not spec_files:
        return {}

    spec_path = spec_files[0]
    fields = {}
    try:
        with open(spec_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        for line in content.splitlines():
            line = line.strip()
            if ":" not in line or line.startswith("#"):
                continue
            parts = line.split(":", 1)
            key = parts[0].strip().lower()
            val = parts[1].strip()

            if key == "name":
                fields["name"] = val
            elif key == "version":
                fields["version"] = val
            elif key in ("source", "source0"):
                fields["source"] = val
            elif key == "url":
                fields["url"] = val
    except Exception as e:
        print(f"Warning: Failed to parse spec file {spec_path}: {e}", file=sys.stderr)

    return fields


def expand_macros(text: str, name: str, version: str) -> str:
    """Expand simple RPM macros %{name}, %name, %{version}, %version."""
    if not text:
        return ""
    if name:
        text = text.replace("%{name}", name).replace("%name", name)
    if version:
        text = text.replace("%{version}", version).replace("%version", version)
    return text


def parse_github_owner_repo(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract owner and repository name from a GitHub URL."""
    if not url:
        return None, None
    suffix = None
    if "github.com/" in url:
        suffix = url.split("github.com/", 1)[1]
    elif "github.com:" in url:
        suffix = url.split("github.com:", 1)[1]
    else:
        return None, None

    parts = suffix.split("/")
    if len(parts) >= 2:
        owner = parts[0]
        repo = parts[1]
        for char in ["?", "#"]:
            if char in repo:
                repo = repo.split(char, 1)[0]
        if repo.endswith(".git"):
            repo = repo[:-4]
        return owner, repo
    return None, None


def fetch_github_release_notes(owner: str, repo: str, version: str) -> str:
    """Fetch release notes from GitHub API for a given tag version."""
    if not owner or not repo or not version:
        return ""

    # Normalize version to try "v" prefixes first (e.g. v0.1.0) and fallback to no prefix (e.g. 0.1.0)
    tags_to_try = []
    if version.startswith(("v", "V")):
        clean_version = version[1:]
        tags_to_try = [version, clean_version]
    else:
        tags_to_try = [f"v{version}", version, f"V{version}"]

    # Append repo-version fallback
    tags_to_try.append(f"{repo}-{version}")

    # Remove duplicates but preserve order
    seen = set()
    unique_tags = []
    for tag in tags_to_try:
        if tag not in seen:
            seen.add(tag)
            unique_tags.append(tag)

    for tag in unique_tags:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
        try:
            headers = {"User-Agent": "changelog-ai"}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "body" in data and data["body"]:
                    return data["body"]
            elif response.status_code in (403, 429):
                print("Warning: GitHub API rate limit hit or forbidden.", file=sys.stderr)
                break
        except Exception:
            pass
    return ""


def get_source_archive_filename(source_val: str, name_val: str, version_val: str) -> Optional[str]:
    """Extract the base source archive filename from raw Source field."""
    if not source_val:
        return None
    expanded = expand_macros(source_val, name_val, version_val)
    if "/" in expanded:
        filename = expanded.split("/")[-1]
    else:
        filename = expanded

    for char in ["#", "?"]:
        if char in filename:
            filename = filename.split(char)[0]

    return filename


def find_local_archive(source_filename: Optional[str]) -> Optional[Path]:
    """Finds the local archive file in the current directory."""
    archive_exts = [".tar.gz", ".tar.xz", ".tgz", ".zip", ".tar.bz2", ".tar"]

    if source_filename:
        p = Path(source_filename)
        if p.exists() and p.is_file():
            return p

        cleaned_name = source_filename
        if "#" in cleaned_name:
            parts = cleaned_name.split("#")
            local_part = parts[-1]
            if local_part.startswith("./"):
                local_part = local_part[2:]
            if Path(local_part).exists():
                return Path(local_part)
            cleaned_name = parts[0]

        base_name = Path(cleaned_name).name
        if Path(base_name).exists():
            return Path(base_name)

    archives = []
    for f in Path(".").iterdir():
        if f.is_file() and any(f.name.endswith(ext) for ext in archive_exts):
            archives.append(f)

    if not archives:
        return None

    if len(archives) == 1:
        return archives[0]

    if source_filename:
        for a in archives:
            if a.name in source_filename or source_filename in a.name:
                return a

    return max(archives, key=lambda p: p.stat().st_size)


def extract_changelog_from_archive(archive_path: Path, n_lines: int = 20) -> str:
    """Extract first n_lines from a changelog file within a zip or tar archive."""
    if not archive_path.exists():
        return ""

    if zipfile.is_zipfile(archive_path):
        try:
            with zipfile.ZipFile(archive_path, "r") as z:
                for name in z.namelist():
                    if is_changelog_file(name):
                        if name.endswith("/"):
                            continue
                        with z.open(name) as f:
                            lines = []
                            for _ in range(n_lines + 2):
                                line = f.readline()
                                if not line:
                                    break
                                lines.append(line.decode("utf-8", errors="ignore"))
                            return extract_latest_changelog("".join(lines))
        except Exception as e:
            print(f"Warning: Failed to read zip archive {archive_path}: {e}", file=sys.stderr)

    try:
        with tarfile.open(archive_path, "r") as t:
            for member in t.getmembers():
                if member.isreg() and is_changelog_file(member.name):
                    f = t.extractfile(member)
                    if f:
                        lines = []
                        for _ in range(n_lines + 2):
                            line = f.readline()
                            if not line:
                                break
                            lines.append(line.decode("utf-8", errors="ignore"))
                        return extract_latest_changelog("".join(lines))
    except Exception:
        pass

    return ""


def clean_spec_diff(spec_diff: str) -> str:
    """Clean the spec diff to show only added and removed lines, excluding Version/Copyright lines."""
    if not spec_diff:
        return ""
    cleaned_lines = []
    for line in spec_diff.splitlines():
        if (line.startswith("+") or line.startswith("-")) \
           and not line.startswith("+Version:") \
           and not line.startswith("-Version:") \
           and "Copyright" not in line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def limit_lines(text: str, max_lines: int = 50) -> str:
    """Limit a text to at most max_lines."""
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines])


def render_template(item: Dict) -> str:
    """Hand-written Jinja2-equivalent renderer for the training dataset format."""
    lines = []

    package = item.get("package")
    old_version = item.get("old_version")
    new_version = item.get("new_version")
    version = item.get("version")

    header = ""
    if package:
        header += f"create structured changelog for package {package}"
    if old_version:
        header += f" from {old_version}"
    if new_version:
        header += f" to {new_version}"
    elif version:
        header += f" {version}"
    header += ":"
    lines.append(header)

    archive_changelog = item.get("archive_changelog")
    if archive_changelog:
        lines.append("changelog:")
        lines.append(archive_changelog)

    github_release_notes = item.get("github_release_notes")
    if github_release_notes:
        lines.append("github release notes:")
        lines.append(github_release_notes)

    added_files = item.get("added_files")
    if added_files:
        lines.append(f"new files: {added_files}")

    removed_files = item.get("removed_files")
    if removed_files:
        lines.append(f"removed files: {removed_files}")

    _service = item.get("_service")
    if _service:
        lines.append("changes in _service:")
        lines.append(_service)

    _multibuild = item.get("_multibuild")
    if _multibuild:
        lines.append("changes in _multibuild:")
        lines.append(_multibuild)

    spec_diff = item.get("spec_diff")
    if spec_diff:
        lines.append("changes in spec file:")
        lines.append(spec_diff)

    rendered = "\n".join(lines)
    return "\n".join(line for line in rendered.splitlines() if line.strip())


def truncate_to_max_length(item: Dict, tokenizer, max_length: int = 1024) -> str:
    """Truncate optional fields via binary search using the model tokenizer."""
    optional_keys = ['archive_changelog', 'github_release_notes', '_service', '_multibuild', 'spec_diff']

    tokenized_optional = {}
    for k in optional_keys:
        if k in item and item[k]:
            tokenized_optional[k] = tokenizer.encode(item[k]).ids

    def get_rendered_text(L: int) -> str:
        temp_item = dict(item)
        for k in optional_keys:
            if k in temp_item and temp_item[k]:
                truncated_ids = tokenized_optional[k][:L]
                temp_item[k] = tokenizer.decode(truncated_ids)

        return render_template(temp_item)

    full_text = get_rendered_text(100000)
    if len(tokenizer.encode(full_text).ids) <= max_length:
        return full_text

    low, high = 0, max_length
    best_text = get_rendered_text(0)

    while low <= high:
        mid = (low + high) // 2
        current_text = get_rendered_text(mid)
        if len(tokenizer.encode(current_text).ids) <= max_length:
            best_text = current_text
            low = mid + 1
        else:
            high = mid - 1

    return best_text


def has_real_content(clean_content: str) -> bool:
    """Check if the clean content has any real descriptions beyond the header/separator."""
    lines = clean_content.splitlines()
    real_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("-------------"):
            continue
        if "@" in line and ("-" in line or "UTC" in line or "20" in line):
            continue
        real_lines.append(line)
    return len(real_lines) > 0


def main():
    """Main entry point for osc-ai-vc."""
    args = parse_args()

    # Parse spec file fields first
    spec_fields = parse_spec_file()

    # Get package and project info
    package = None
    if Path(".osc/_package").exists():
        try:
            with open(".osc/_package", "r") as f:
                package = f.read().strip()
        except Exception as e:
            print(f"Warning: Error reading .osc/_package: {e}", file=sys.stderr)

    if not package:
        package = spec_fields.get("name")

    if not package:
        print("Error: Could not determine package name.", file=sys.stderr)
        print("Run this command from within an osc package checkout or a directory containing a .spec file", file=sys.stderr)
        sys.exit(1)

    project = "unknown"
    if Path(".osc/_project").exists():
        try:
            with open(".osc/_project", "r") as f:
                project = f.read().strip()
        except Exception:
            pass

    print(f"Generating AI changelog for package: {package} (project: {project})")
    print(f"Using model: t5-{args.model_size} (CTranslate2)")
    print()

    # Create a simple args object for compatibility with get_changes
    class SimpleArgs:
        stdin = False
        repo_path = "."
        commit_range = None

    simple_args = SimpleArgs()

    # Get changes (raw unified diff of all modified files)
    try:
        changes = get_changes(simple_args)
    except Exception as e:
        print(f"Error getting changes: {e}", file=sys.stderr)
        sys.exit(1)

    if not changes.strip():
        print("Error: No changes detected", file=sys.stderr)
        print("Make some changes to the package first", file=sys.stderr)
        sys.exit(1)

    # Parse multi-file diffs
    file_diffs = parse_multi_file_diff(changes)

    # Identify diffs for specific files
    spec_diff_raw = ""
    service_diff_raw = ""
    multibuild_diff_raw = ""

    for filename, diff_content in file_diffs.items():
        if filename.endswith(".spec"):
            spec_diff_raw = diff_content
        elif filename == "_service":
            service_diff_raw = diff_content
        elif filename == "_multibuild":
            multibuild_diff_raw = diff_content

    # Determine added and removed files
    added, removed = get_added_removed_files()
    added_files = [f for f in added if not f.endswith(".sig")]
    removed_files = [f for f in removed if not f.endswith(".sig")]

    # Check for version update and extract old/new versions from spec diff
    has_version_update = False
    old_version = None
    new_version = None

    if spec_diff_raw:
        old_v_match = re.search(r'^-Version:\s*(.*)', spec_diff_raw, re.MULTILINE)
        new_v_match = re.search(r'^\+Version:\s*(.*)', spec_diff_raw, re.MULTILINE)
        if old_v_match:
            old_version = old_v_match.group(1).strip()
        if new_v_match:
            new_version = new_v_match.group(1).strip()
        if old_v_match and new_v_match:
            has_version_update = True

    # Use version from spec file as fallback
    version = spec_fields.get("version")

    # Expand macros in spec fields
    spec_name = spec_fields.get("name", package)
    spec_version = new_version or version
    spec_source_raw = spec_fields.get("source")
    spec_url_raw = spec_fields.get("url")

    expanded_source = expand_macros(spec_source_raw, spec_name, spec_version)
    expanded_url = expand_macros(spec_url_raw, spec_name, spec_version)

    # Prepare fields
    github_release_notes = ""
    archive_changelog = ""

    # If there is a version update, we fetch release notes and extract archive changelog
    if has_version_update:
        # Get GitHub owner/repo
        owner, repo = parse_github_owner_repo(expanded_url)
        if not owner or not repo:
            owner, repo = parse_github_owner_repo(expanded_source)

        if owner and repo:
            print(f"Fetching GitHub release notes for {owner}/{repo} (tag: {new_version})...", file=sys.stderr)
            github_release_notes = fetch_github_release_notes(owner, repo, new_version)
            github_release_notes = limit_lines(github_release_notes, max_lines=50)

        # Try to locate local archive and extract internal changelog
        source_filename = get_source_archive_filename(spec_source_raw, spec_name, spec_version)
        local_archive = find_local_archive(source_filename)
        if local_archive:
            print(f"Extracting changelog from source archive: {local_archive.name}...", file=sys.stderr)
            archive_changelog = extract_changelog_from_archive(local_archive, n_lines=50)

    # Clean spec diff (keep only +/- lines, exclude Version and Copyright)
    cleaned_spec_diff = clean_spec_diff(spec_diff_raw)

    # Clean service and multibuild diffs
    cleaned_service = clean_obs_diff(service_diff_raw)
    cleaned_multibuild = clean_obs_diff(multibuild_diff_raw)

    # Build the item dict
    item = {
        "package": package,
        "old_version": old_version,
        "new_version": new_version,
        "version": version,
        "added_files": added_files if added_files else None,
        "removed_files": removed_files if removed_files else None,
        "_service": cleaned_service if cleaned_service else None,
        "_multibuild": cleaned_multibuild if cleaned_multibuild else None,
        "spec_diff": cleaned_spec_diff if cleaned_spec_diff else None,
        "archive_changelog": archive_changelog if archive_changelog else None,
        "github_release_notes": github_release_notes if github_release_notes else None,
    }

    # Load model
    print("Loading model...", file=sys.stderr)
    try:
        generator = ChangelogGenerator(
            model_size=args.model_size,
            quantization=args.quantization,
            device=args.device,
            model_path=args.model_path,
        )

        # Token-truncate item using binary search
        print("Preparing input data...", file=sys.stderr)
        input_text = truncate_to_max_length(item, generator.tokenizer, max_length=1024)

        print("Generating changelog...", file=sys.stderr)
        generated = generator.generate(input_text, beam_size=6)

    except Exception as e:
        print(f"Error during generation: {e}", file=sys.stderr)
        sys.exit(1)

    # Create changelog entry
    changelog_entry = create_changelog_entry(generated, input_text)

    # Open editor
    final_content = open_editor(changelog_entry, no_edit=False)

    # Strip comments from the final edited content
    clean_content = "\n".join(
        line for line in final_content.splitlines()
        if not line.strip().startswith("#")
    ).strip()

    # Check if there is any real content before writing
    if not has_real_content(clean_content):
        print("Warning: No changelog description provided. Aborting update to .changes file.", file=sys.stderr)
        sys.exit(0)

    # Find and update the local .changes file
    changes_files = list(Path(".").glob("*.changes"))
    if not changes_files:
        print("Error: No .changes file found in the current directory.", file=sys.stderr)
        sys.exit(1)

    changes_file = changes_files[0]
    try:
        with open(changes_file, "r", encoding="utf-8", errors="ignore") as f:
            existing_content = f.read()

        # Prepend the new clean entry to the existing changes file
        new_content = clean_content + "\n\n" + existing_content

        with open(changes_file, "w", encoding="utf-8") as f:
            f.write(new_content)

        print(f"Successfully updated changes file: {changes_file.name}")
        print()
    except Exception as e:
        print(f"Error writing to changes file {changes_file.name}: {e}", file=sys.stderr)
        sys.exit(1)

    print()
    print("Changelog generated and saved successfully!")
    print()
    print("Next steps:")
    print("  1. Review your changes: osc diff")
    print("  2. Commit your changes: osc commit")


if __name__ == "__main__":
    main()
