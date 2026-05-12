"""Model loading and changelog generation."""

import os
import re
import sys
from pathlib import Path

try:
    import ctranslate2
    from tokenizers import Tokenizer
    import requests
except ImportError:
    raise ImportError(
        "Required packages not installed. "
        "Install with: pip install ctranslate2 tokenizers requests"
    )


def get_model_cache_dir():
    """Get the model cache directory using XDG standards."""
    # Try XDG_CACHE_HOME first
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        cache_dir = Path(xdg_cache) / "changelog-ai"
    else:
        # Fall back to ~/.local/share
        cache_dir = Path.home() / ".local" / "share" / "changelog-ai"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def download_file(url, dest_path, desc="Downloading"):
    """Download a file with progress indication."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))

        with open(dest_path, 'wb') as f:
            if total_size == 0:
                f.write(response.content)
                print(f"✓ {desc}: {dest_path.name}")
            else:
                downloaded = 0
                chunk_size = 8192
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        # Simple progress indicator
                        percent = (downloaded / total_size) * 100
                        print(f"\r  {desc}: {dest_path.name} [{percent:.1f}%]", end='', file=sys.stderr)
                print(f"\r✓ {desc}: {dest_path.name} [{total_size/1024/1024:.1f} MB]", file=sys.stderr)

        return True
    except Exception as e:
        print(f"\n✗ Failed to download {url}: {e}", file=sys.stderr)
        if dest_path.exists():
            dest_path.unlink()
        return False


def download_model_from_hf(model_size, quantization, cache_dir):
    """Download model files from Hugging Face."""
    repo_id = "mslacken/t5-finetune-changelog"
    base_url = f"https://huggingface.co/{repo_id}/resolve/main"

    print(f"Downloading t5-{model_size} model files from Hugging Face...", file=sys.stderr)

    # Files to download
    files_to_download = [
        # Tokenizer files
        (f"t5-{model_size}/tokenizer.json", cache_dir / f"t5-{model_size}" / "tokenizer.json"),
        (f"t5-{model_size}/tokenizer_config.json", cache_dir / f"t5-{model_size}" / "tokenizer_config.json"),
        # CTranslate2 model files
        (f"ct2_models/t5-{model_size}-ct2-{quantization}/config.json",
         cache_dir / "ct2_models" / f"t5-{model_size}-ct2-{quantization}" / "config.json"),
        (f"ct2_models/t5-{model_size}-ct2-{quantization}/model.bin",
         cache_dir / "ct2_models" / f"t5-{model_size}-ct2-{quantization}" / "model.bin"),
        (f"ct2_models/t5-{model_size}-ct2-{quantization}/shared_vocabulary.json",
         cache_dir / "ct2_models" / f"t5-{model_size}-ct2-{quantization}" / "shared_vocabulary.json"),
    ]

    success = True
    for remote_path, local_path in files_to_download:
        if local_path.exists():
            print(f"✓ Already cached: {local_path.name}", file=sys.stderr)
            continue

        url = f"{base_url}/{remote_path}"
        if not download_file(url, local_path, f"Downloading {remote_path.split('/')[-1]}"):
            success = False
            break

    if success:
        print(f"\n✓ Model t5-{model_size} downloaded successfully!", file=sys.stderr)

    return success


class ChangelogGenerator:
    """Wrapper for T5 changelog generation models using CTranslate2."""

    def __init__(
        self,
        model_size="large",
        quantization="int8",
        device="cpu",
        model_path=None,
        auto_download=True,
    ):
        """
        Initialize the changelog generator.

        Args:
            model_size: Model size (small/base/large)
            quantization: CTranslate2 quantization level (int8/float16/float32/int8_float16)
            device: Device to run on (cpu/cuda)
            model_path: Path to model directory (overrides default cache)
            auto_download: Automatically download models if not found
        """
        self.model_size = model_size
        self.quantization = quantization
        self.device = device
        self.auto_download = auto_download

        # Determine model path
        if model_path is None:
            self.model_path = get_model_cache_dir()
        else:
            self.model_path = Path(model_path)

        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self):
        """Load model using CTranslate2 backend."""
        model_path = (
            self.model_path
            / "ct2_models"
            / f"t5-{self.model_size}-ct2-{self.quantization}"
        )
        tokenizer_path = self.model_path / f"t5-{self.model_size}" / "tokenizer.json"

        # Check if model exists, download if needed
        if not model_path.exists() or not tokenizer_path.exists():
            if self.auto_download:
                print(f"Model not found locally. Downloading from Hugging Face...", file=sys.stderr)
                if not download_model_from_hf(self.model_size, self.quantization, self.model_path):
                    raise FileNotFoundError(
                        f"Failed to download model. Please check your internet connection or "
                        f"manually download from https://huggingface.co/mslacken/t5-finetune-changelog"
                    )
            else:
                raise FileNotFoundError(
                    f"Model not found at {model_path}. "
                    f"Set auto_download=True or download manually from "
                    f"https://huggingface.co/mslacken/t5-finetune-changelog"
                )

        # Verify files exist after download
        if not model_path.exists():
            raise FileNotFoundError(f"CTranslate2 model not found at {model_path}")
        if not tokenizer_path.exists():
            raise FileNotFoundError(f"Tokenizer not found at {tokenizer_path}")

        self.model = ctranslate2.Translator(str(model_path), device=self.device)
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def _decode_changelog(self, output_tokens):
        """Decode model output while preserving newlines."""
        # Convert token strings to IDs for decoding
        token_ids = []
        for token in output_tokens:
            token_id = self.tokenizer.token_to_id(token)
            if token_id is not None:
                token_ids.append(token_id)

        # Decode using the tokenizers library
        decoded = self.tokenizer.decode(token_ids)

        # Remove special tokens. T5 pads with <pad> and ends with </s>.
        # extra_id_* are used for span corruption.
        decoded = decoded.replace("<pad>", "")
        decoded = decoded.replace("</s>", "")
        decoded = re.sub(r"<extra_id_\d+>", "", decoded)

        return decoded.strip()

    def generate(self, input_text, beam_size=6):
        """
        Generate changelog from input text.

        Args:
            input_text: Input diff or changes
            beam_size: Beam size for generation

        Returns:
            Generated changelog text
        """
        # Guess 4 chars per token. 1024 tokens is ~4096 chars.
        # We truncate the input text to roughly 1000 tokens to avoid exceeding model limits.
        # T5 expects </s> at the end of input.
        input_text_truncated = input_text[:4000] + "</s>"

        # Encode text to tokens using tokenizers library
        encoding = self.tokenizer.encode(input_text_truncated)
        input_tokens = encoding.tokens

        results = self.model.translate_batch(
            [input_tokens],
            beam_size=beam_size,
            max_decoding_length=512,
            no_repeat_ngram_size=4,
            max_input_length=1024,
        )

        return self._decode_changelog(results[0].hypotheses[0])
