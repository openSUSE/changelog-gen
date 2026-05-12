"""Model loading and changelog generation."""

import re
from pathlib import Path

try:
    import ctranslate2
    from tokenizers import Tokenizer
except ImportError:
    raise ImportError(
        "ctranslate2 or tokenizers not installed. "
        "Install with: pip install ctranslate2 tokenizers"
    )


class ChangelogGenerator:
    """Wrapper for T5 changelog generation models using CTranslate2."""

    def __init__(
        self,
        model_size="large",
        quantization="int8",
        device="cpu",
        model_path=None,
    ):
        """
        Initialize the changelog generator.

        Args:
            model_size: Model size (small/base/large)
            quantization: CTranslate2 quantization level
            device: Device to run on (cpu/cuda)
            model_path: Path to model directory
        """
        self.model_size = model_size
        self.quantization = quantization
        self.device = device

        # Default model path
        if model_path is None:
            model_path = Path.home() / "scratch" / "t5-finetune-changelog"
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
        # T5 tokenizer uses Hugging Face tokenizer.json format
        tokenizer_path = self.model_path / f"t5-{self.model_size}" / "tokenizer.json"

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
