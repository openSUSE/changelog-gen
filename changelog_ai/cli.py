"""Command-line interface for AI changelog generator."""

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .model import ChangelogGenerator


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate changelog entries using AI from code changes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from current osc package
  %(prog)s

  # Use specific model
  %(prog)s --model-size large --backend ctranslate2

  # Generate from git commit range
  %(prog)s --commit-range HEAD~5..HEAD

  # Read diff from stdin
  git diff HEAD~3..HEAD | %(prog)s --stdin

  # Use different repo path
  %(prog)s --repo-path /path/to/package

  # Use custom model path
  %(prog)s --model-path /path/to/models
        """,
    )

    parser.add_argument(
        "--model-size",
        choices=["small", "base", "large"],
        default="large",
        help="Model size (default: large, recommended for quality)",
    )

    parser.add_argument(
        "--quantization",
        choices=["float32", "float16", "int8_float16", "int8"],
        default="int8",
        help="CTranslate2 quantization (default: int8, CPU/GPU compatible)",
    )

    parser.add_argument(
        "--commit-range", help="Git commit range (e.g., HEAD~5..HEAD)"
    )

    parser.add_argument(
        "--stdin", action="store_true", help="Read diff from stdin instead of repo"
    )

    parser.add_argument(
        "--repo-path", default=".", help="Path to repository (default: current directory)"
    )

    parser.add_argument(
        "--model-path",
        help="Path to T5 model directory (default: $XDG_CACHE_HOME/changelog-ai or ~/.local/share/changelog-ai)",
    )

    parser.add_argument(
        "--device",
        choices=["cpu", "cuda"],
        default="cpu",
        help="Device to run inference on (default: cpu)",
    )

    parser.add_argument(
        "--beam-size",
        type=int,
        default=6,
        help="Beam size for generation (default: 6)",
    )

    parser.add_argument(
        "--no-edit", action="store_true", help="Skip editor and output to stdout"
    )

    return parser.parse_args()


def get_changes(args):
    """Extract changes from repo or stdin."""
    if args.stdin:
        print("Reading changes from stdin...", file=sys.stderr)
        return sys.stdin.read()

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    os.chdir(repo_path)

    if args.commit_range:
        print(
            f"Getting changes from git range: {args.commit_range}", file=sys.stderr
        )
        try:
            result = subprocess.run(
                ["git", "diff", args.commit_range],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            print(f"Error running git diff: {e}", file=sys.stderr)
            sys.exit(1)

    # Try osc diff
    print("Getting changes from osc...", file=sys.stderr)
    try:
        result = subprocess.run(
            ["osc", "diff"], capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        # Fallback to git diff if osc fails
        print("osc diff failed, trying git diff...", file=sys.stderr)
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"], capture_output=True, text=True, check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            print(
                f"Error: Could not get changes from osc or git: {e}",
                file=sys.stderr,
            )
            sys.exit(1)


def get_package_info():
    """Get package name and version from osc."""
    try:
        # Try to get package name from osc
        result = subprocess.run(
            ["osc", "info"], capture_output=True, text=True, check=True
        )

        package_name = None
        for line in result.stdout.split("\n"):
            if line.startswith("Package:"):
                package_name = line.split(":", 1)[1].strip()
                break

        return package_name
    except:
        return None


def create_changelog_entry(generated_text, original_changes):
    """Create a formatted changelog entry with headers and commented input."""
    now = datetime.now()
    date_str = now.strftime("%a %b %d %H:%M:%S %Z %Y")

    # Try to get user info from git or osc config
    try:
        result = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True
        )
        username = result.stdout.strip()

        result = subprocess.run(
            ["git", "config", "user.email"], capture_output=True, text=True
        )
        email = result.stdout.strip()

        author = f"{username} <{email}>"
    except:
        author = "unknown <unknown@localhost>"

    # Create the entry
    lines = [
        "-" * 67,
        f"{date_str} - {author}",
        "",
        "# AI-generated changelog entry:",
        generated_text,
        "",
        "# Original changes used for generation:",
    ]

    # Add original changes as comments (truncate if too long)
    change_lines = original_changes.split("\n")
    if len(change_lines) > 100:
        # Show first 50 and last 50 lines if diff is very long
        for line in change_lines[:50]:
            lines.append(f"# {line}")
        lines.append("# ... (truncated, see full diff with osc diff or git diff) ...")
        for line in change_lines[-50:]:
            lines.append(f"# {line}")
    else:
        for line in change_lines:
            lines.append(f"# {line}")

    lines.append("-" * 67)
    lines.append("")

    return "\n".join(lines)


def open_editor(content, no_edit=False):
    """Open editor for the user to review and edit the changelog."""
    if no_edit:
        print(content)
        return content

    # Get editor from environment or use default
    editor = os.environ.get("EDITOR", "vim")

    # Create temporary file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".changes", delete=False
    ) as f:
        f.write(content)
        temp_file = f.name

    try:
        # Open editor
        subprocess.run([editor, temp_file], check=True)

        # Read the edited content
        with open(temp_file, "r") as f:
            edited_content = f.read()

        return edited_content
    finally:
        # Clean up
        os.unlink(temp_file)


def main():
    """Main entry point."""
    args = parse_args()

    # Get changes
    changes = get_changes(args)

    if not changes.strip():
        print("Error: No changes detected", file=sys.stderr)
        sys.exit(1)

    # Prepare input for model
    package_info = get_package_info()
    if package_info:
        input_text = f"create structured changelog for package {package_info}:\n{changes}"
    else:
        input_text = f"create structured changelog:\n{changes}"

    # Load model and generate
    print(
        f"Loading model: t5-{args.model_size} using CTranslate2 backend...",
        file=sys.stderr,
    )

    try:
        generator = ChangelogGenerator(
            model_size=args.model_size,
            quantization=args.quantization,
            device=args.device,
            model_path=args.model_path,
        )

        print("Generating changelog...", file=sys.stderr)
        generated = generator.generate(input_text, beam_size=args.beam_size)

    except Exception as e:
        print(f"Error during generation: {e}", file=sys.stderr)
        sys.exit(1)

    # Create changelog entry
    changelog_entry = create_changelog_entry(generated, changes)

    # Open editor or print
    final_content = open_editor(changelog_entry, args.no_edit)

    if not args.no_edit:
        print("\nFinal changelog entry:", file=sys.stderr)
        print(final_content)


if __name__ == "__main__":
    main()
