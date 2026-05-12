# AI Changelog Generator

AI-powered changelog generator that uses fine-tuned T5 models to create human-readable changelog entries from code changes. Integrates with both `osc` (Open Build Service) and `git`.

It is mostly a thin wrapper to pipe the diff via `ctranslate2` to a the fine tuned model, which is downloaded automatically. The model itself should be able to run on machines with 1GB of main memory.

This software was mostly vibe coded.

## Installation

### Quick Install

```bash
# Install from source
pip install .

# Or install in development mode
pip install -e .
```

### Dependencies

- Python >= 3.8
- `ctranslate2` - Fast inference engine
- `tokenizers` - HuggingFace tokenizers library
- `requests` - For downloading models

### Model Storage

Models are automatically downloaded on first use and stored in:
- `$XDG_CACHE_HOME/changelog-ai/` (if XDG_CACHE_HOME is set)
- `~/.local/share/changelog-ai/` (default)

You can specify a custom location with `--model-path`.


## Usage

After installation, two commands are available:

### changelog-ai

Main command for generating changelogs:

```bash
# Generate from current osc package or git repository
changelog-ai

# Use specific model size
changelog-ai --model-size large

# Skip editor and output to stdout
changelog-ai --no-edit

# Use GPU acceleration (if available)
changelog-ai --device cuda
```

### osc-ai-vc

OSC-specific wrapper (similar to `osc vc`):

```bash
# In an osc package directory
cd ~/osc/home:user/mypackage
osc-ai-vc

# With custom model settings
osc-ai-vc --model-size base --quantization int8
```

### Legacy Standalone Scripts

For non-installed usage, standalone scripts are available in the root directory:

```bash
# Run without installation
./changelog-ai --help
./osc-ai-vc --help
```

### Basic Usage Examples

```bash
# Or run as a Python module
python -m changelog_ai
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
git diff HEAD~3..HEAD | changelog-ai --stdin

# Use with osc
osc diff | changelog-ai --stdin

# Combine with other tools
git log -p --reverse HEAD~5..HEAD | changelog-ai --stdin
```

### Advanced Options

```bash
# Use different repository path
changelog-ai --repo-path /path/to/package

# Custom beam size for generation quality
changelog-ai --beam-size 8

# Use different quantization (CTranslate2 only)
changelog-ai --quantization int8_float16  # GPU only, faster

# Custom model path
changelog-ai --model-path /custom/path/to/models
```

## Command-Line Options

### Main Options

| Option | Default | Description |
|--------|---------|-------------|
| `--model-size` | `large` | Model size: small/base/large |
| `--quantization` | `int8` | CTranslate2 quantization: float32/float16/int8_float16/int8 |
| `--device` | `cpu` | Device: cpu/cuda |
| `--beam-size` | `6` | Beam size for generation quality |
| `--no-edit` | - | Skip editor, output to stdout |
| `--model-path` | See above | Custom path to model directory |

### Input Sources

| Option | Description |
|--------|-------------|
| (none) | Auto-detect osc package or git repository |
| `--commit-range RANGE` | Git commit range (e.g., HEAD~5..HEAD) |
| `--stdin` | Read diff from stdin |
| `--repo-path PATH` | Path to repository (default: current directory) |


## Output Format

The script generates a changelog entry with:

1. **Header**: Date, time, and author info
2. **Generated changelog**: AI-generated human-readable entry
3. **Original changes**: The input diff/changes as comments for verification

Example output:

```
-------------------------------------------------------------------
Tue May 12 12:00:00 UTC 2026 - user@example.com

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

### First Run - Model Download

On first use, models will be automatically downloaded from Hugging Face:

```
Model not found locally. Downloading from Hugging Face...
✓ Downloading tokenizer.json [2.3 MB]
✓ Downloading model.bin [740.4 MB]
...
✓ Model t5-large downloaded successfully!
```

This is a one-time download. Subsequent runs will use the cached model.

### Manual Model Download

If automatic download fails, you can manually download from:
https://huggingface.co/mslacken/t5-finetune-changelog

Place files in `~/.local/share/changelog-ai/` following this structure:

```
~/.local/share/changelog-ai/
├── t5-{size}/
│   ├── tokenizer.json
│   └── tokenizer_config.json
└── ct2_models/
    └── t5-{size}-ct2-{quantization}/
        ├── config.json
        ├── model.bin
        └── shared_vocabulary.json
```

### Custom Model Path

Specify a custom model location:

```bash
changelog-ai --model-path /path/to/models
```

### CUDA Errors

If you get CUDA errors with `--device cuda`, fall back to CPU:

```bash
changelog-ai --device cpu
```

### No Changes Detected

Ensure you're in a git repository or osc package directory with uncommitted changes, or use `--stdin` to provide changes manually.

### Editor Not Opening

Set your preferred editor:

```bash
export EDITOR=nano
changelog-ai
```

Or skip the editor entirely:

```bash
changelog-ai --no-edit > changelog.txt
```

## Integration Examples

### Example 1: Basic osc workflow

```bash
cd ~/osc/home:user/mypackage
# Make changes to spec file
changelog-ai
# Review and save in editor
osc commit
```

### Example 2: Generate from specific commits

```bash
changelog-ai --commit-range v1.0.0..v1.1.0 --no-edit > release-notes.txt
```

### Example 3: Pipeline with filtering

```bash
git diff HEAD~10..HEAD -- '*.spec' '*.changes' | changelog-ai --stdin
```

### Example 4: GPU-accelerated with large model

```bash
changelog-ai --model-size large --device cuda --quantization int8_float16 --beam-size 8
```

## Development

### Run Without Installation

```bash
# Using Python module
python3 -m changelog_ai

# Using legacy scripts
./changelog-ai
./osc-ai-vc
```

### Running Tests

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black changelog_ai/
isort changelog_ai/
```

## License

Apache 2.0 (same as the T5 model)

## Related Links

- **Model Repository**: https://huggingface.co/mslacken/t5-finetune-changelog
- **Issue Tracker**: https://github.com/mslacken/changelog-ai/issues
- **Source Code**: https://github.com/mslacken/changelog-ai
