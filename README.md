# AI Changelog Generator

AI-powered changelog generator that uses fine-tuned T5 models to create human-readable changelog entries from code changes. Integrates with both `osc` (Open Build Service) and `git`.

## Features

- Uses fine-tuned T5 models (small/base/large) for changelog generation
- Supports both CTranslate2 (2-4x faster) and Transformers backends
- Integrates with `osc` and `git` workflows
- Opens editor for review (like `osc vc`)
- Includes original changes as comments for verification
- Supports multiple input sources (osc, git commit ranges, stdin)
- Installable via pip/wheel

## Installation

### Quick Install

```bash
# Install from source with all dependencies
pip install ".[all]"

# Or install with only CTranslate2 (recommended)
pip install ".[ctranslate2]"
```

### Build and Install from Wheel

```bash
# Build the package
./build-package.sh

# Install the built wheel
pip install dist/changelog_ai-*.whl[all]
```

For detailed installation instructions, see [INSTALL.md](INSTALL.md).

For building and publishing, see [BUILD.md](BUILD.md).

### Model Setup

The script expects the T5 models to be available at:
```
/home/chris/scratch/t5-finetune-changelog/
├── t5-small/
├── t5-base/
├── t5-large/
└── ct2_models/
    ├── t5-base-ct2-int8/
    ├── t5-large-ct2-int8/
    └── ...
```

If using a different location, specify with `--model-path`.

## Package Structure

```
changelog-gen/
├── pyproject.toml          # Package configuration
├── setup.py                # Build configuration
├── MANIFEST.in             # Package manifest
├── LICENSE                 # Apache 2.0 license
├── README.md               # This file
├── INSTALL.md              # Installation guide
├── BUILD.md                # Building and publishing guide
├── requirements.txt        # Dependencies
├── build-package.sh        # Quick build script
├── changelog_ai/           # Main package
│   ├── __init__.py         # Package initialization
│   ├── __main__.py         # Allow python -m changelog_ai
│   ├── cli.py              # Command-line interface
│   ├── model.py            # Model loading and generation
│   └── osc_wrapper.py      # OSC integration wrapper
├── changelog-ai            # Legacy standalone script
├── osc-ai-vc               # Legacy OSC wrapper script
└── example-test.sh         # Test script
```

## Usage

### Basic Usage

```bash
# After installation, use the command
changelog-ai

# Or run as a Python module
python -m changelog_ai

# Use specific model size
./changelog-ai --model-size large

# Use transformers backend instead of CTranslate2
./changelog-ai --backend transformers
```

### Git Integration

```bash
# Generate from git commit range
./changelog-ai --commit-range HEAD~5..HEAD

# Generate from last 3 commits
./changelog-ai --commit-range HEAD~3..HEAD

# Generate from specific commits
./changelog-ai --commit-range abc123..def456
```

### Pipeline Usage

```bash
# Read diff from stdin
git diff HEAD~3..HEAD | ./changelog-ai --stdin

# Use with osc
osc diff | ./changelog-ai --stdin

# Combine with other tools
git log -p --reverse HEAD~5..HEAD | ./changelog-ai --stdin
```

### Advanced Options

```bash
# Use different repository path
./changelog-ai --repo-path /path/to/package

# Skip editor and output to stdout
./changelog-ai --no-edit

# Use GPU acceleration
./changelog-ai --device cuda

# Custom beam size for generation quality
./changelog-ai --beam-size 8

# Use different quantization (CTranslate2 only)
./changelog-ai --quantization int8_float16  # GPU only, faster
```

## Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--model-size` | `large` | Model size: small/base/large (large recommended) |
| `--backend` | `ctranslate2` | Backend: transformers/ctranslate2 |
| `--quantization` | `int8` | CTranslate2 quantization: float32/float16/int8_float16/int8 |
| `--commit-range` | - | Git commit range (e.g., HEAD~5..HEAD) |
| `--stdin` | - | Read diff from stdin |
| `--repo-path` | `.` | Path to repository |
| `--model-path` | See above | Path to T5 model directory |
| `--device` | `cpu` | Device: cpu/cuda |
| `--beam-size` | `6` | Beam size for generation |
| `--no-edit` | - | Skip editor, output to stdout |

## Model Selection

### Recommended: t5-large with CTranslate2 int8

```bash
./changelog-ai --model-size large --backend ctranslate2 --quantization int8
```

This provides the best quality-to-speed ratio and works on both CPU and GPU.

### Performance Comparison

| Model | Backend | Size | Speed | Quality |
|-------|---------|------|-------|---------|
| t5-large | ctranslate2 int8 | ~770 MB | Fast | Best |
| t5-base | ctranslate2 int8 | ~220 MB | Very Fast | Good |
| t5-large | transformers | ~2.8 GB | Slow | Best |
| t5-small | Any | ~231 MB | Very Fast | Poor (hallucinates) |

**Note**: t5-small is NOT recommended as it tends to generate hallucinated changelogs.

### GPU Acceleration

For GPU users, use int8_float16 quantization for best performance:

```bash
./changelog-ai --device cuda --quantization int8_float16
```

## Output Format

The script generates a changelog entry with:

1. **Header**: Date, time, and author info
2. **Generated changelog**: AI-generated human-readable entry
3. **Original changes**: The input diff/changes as comments for verification

Example output:

```
-------------------------------------------------------------------
Mon May 11 15:30:00 UTC 2026 - user@example.com

# AI-generated changelog entry:
- update to version 4.3.0rc2:
  * Provision interface is not tied to 'eth0' anymore
  * Creating of '/etc/exports' can now be disabled
  * All configuration files are now populated from templates

# Original changes used for generation:
# diff --git a/CHANGELOG.md b/CHANGELOG.md
# ... (full diff as comments)
-------------------------------------------------------------------
```

You can then review, edit, and save this to your `.changes` file.

## Integration with osc Workflow

```bash
# 1. Make changes to your package
cd /path/to/osc/package
# ... edit files ...

# 2. Generate changelog
/path/to/changelog-ai

# 3. Review in editor, save, and exit

# 4. Commit the changes
osc commit

# Or use osc vc to edit the .changes file manually
osc vc
```

## Troubleshooting

### Model not found

Ensure the T5 models are downloaded and available at the expected location, or specify `--model-path`:

```bash
./changelog-ai --model-path /custom/path/to/models
```

### CUDA errors

If you get CUDA errors with `--device cuda`, fall back to CPU:

```bash
./changelog-ai --device cpu
```

### No changes detected

Ensure you're in a git repository or osc package directory with uncommitted changes, or use `--stdin` to provide changes manually.

### Editor not opening

Set your preferred editor:

```bash
export EDITOR=nano
./changelog-ai
```

Or skip the editor entirely:

```bash
./changelog-ai --no-edit > changelog.txt
```

## Examples

### Example 1: Basic osc workflow

```bash
cd ~/osc/home:user/mypackage
# Make changes to spec file
./changelog-ai
# Review and save in editor
osc commit
```

### Example 2: Generate from specific commits

```bash
./changelog-ai --commit-range v1.0.0..v1.1.0 --no-edit > release-notes.txt
```

### Example 3: Pipeline with filtering

```bash
git diff HEAD~10..HEAD -- '*.spec' '*.changes' | ./changelog-ai --stdin
```

### Example 4: GPU-accelerated with large model

```bash
./changelog-ai --model-size large --device cuda --quantization int8_float16 --beam-size 8
```

## License

Apache 2.0 (same as the T5 model)

## Credits

- Fine-tuned T5 models by Christian Goll
- Model: [mslacken/t5-finetune-changelog](https://huggingface.co/mslacken/t5-finetune-changelog)
