#!/usr/bin/env python3
"""OSC wrapper for AI changelog generation."""

import argparse
import os
import sys
from pathlib import Path

from .cli import get_changes, get_package_info, create_changelog_entry, open_editor
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
        "--backend",
        choices=["transformers", "ctranslate2"],
        default="ctranslate2",
        help="Backend: transformers/ctranslate2 (default: ctranslate2)",
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


def main():
    """Main entry point for osc-ai-vc."""
    args = parse_args()

    # Check if we're in an osc package directory
    if not Path(".osc/_package").exists():
        print("Error: Not in an osc package directory", file=sys.stderr)
        print("Run this command from within an osc package checkout", file=sys.stderr)
        sys.exit(1)

    # Get package and project info
    try:
        with open(".osc/_package", "r") as f:
            package = f.read().strip()

        project = "unknown"
        if Path(".osc/_project").exists():
            with open(".osc/_project", "r") as f:
                project = f.read().strip()

        print(f"Generating AI changelog for package: {package} (project: {project})")
        print(f"Using model: t5-{args.model_size}, backend: {args.backend}")
        print()
    except Exception as e:
        print(f"Error reading osc metadata: {e}", file=sys.stderr)
        sys.exit(1)

    # Create a simple args object for compatibility with get_changes
    class SimpleArgs:
        stdin = False
        repo_path = "."
        commit_range = None

    simple_args = SimpleArgs()

    # Get changes
    try:
        changes = get_changes(simple_args)
    except Exception as e:
        print(f"Error getting changes: {e}", file=sys.stderr)
        sys.exit(1)

    if not changes.strip():
        print("Error: No changes detected", file=sys.stderr)
        print("Make some changes to the package first", file=sys.stderr)
        sys.exit(1)

    # Prepare input
    input_text = f"create structured changelog for package {package}:\n{changes}"

    # Load model and generate
    print(f"Loading model...", file=sys.stderr)

    try:
        generator = ChangelogGenerator(
            model_size=args.model_size,
            backend=args.backend,
            quantization=args.quantization,
            device=args.device,
            model_path=args.model_path,
        )

        print("Generating changelog...", file=sys.stderr)
        generated = generator.generate(input_text, beam_size=6)

    except Exception as e:
        print(f"Error during generation: {e}", file=sys.stderr)
        sys.exit(1)

    # Create changelog entry
    changelog_entry = create_changelog_entry(generated, changes)

    # Open editor
    final_content = open_editor(changelog_entry, no_edit=False)

    print()
    print("Changelog generated successfully!")
    print()
    print("Next steps:")
    print("  1. Review the generated changelog above")
    print("  2. Edit your .changes file: osc vc")
    print("  3. Commit your changes: osc commit")


if __name__ == "__main__":
    main()
