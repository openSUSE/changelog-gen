"""Model loading and changelog generation."""

import re
from pathlib import Path


class ChangelogGenerator:
    """Wrapper for T5 changelog generation models."""

    def __init__(
        self,
        model_size="large",
        backend="ctranslate2",
        quantization="int8",
        device="cpu",
        model_path=None,
    ):
        """
        Initialize the changelog generator.

        Args:
            model_size: Model size (small/base/large)
            backend: Backend to use (ctranslate2/transformers)
            quantization: CTranslate2 quantization level
            device: Device to run on (cpu/cuda)
            model_path: Path to model directory
        """
        self.model_size = model_size
        self.backend = backend
        self.quantization = quantization
        self.device = device

        # Default model path
        if model_path is None:
            model_path = Path.home() / "scratch" / "t5-finetune-changelog"
        self.model_path = Path(model_path)

        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model_transformers(self):
        """Load model using transformers backend."""
        try:
            from transformers import AutoTokenizer, T5ForConditionalGeneration
        except ImportError:
            raise ImportError(
                "transformers not installed. "
                "Install with: pip install transformers torch"
            )

        model_path = self.model_path / f"t5-{self.model_size}"

        if not model_path.exists():
            raise FileNotFoundError(f"Model not found at {model_path}")

        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        self.model = T5ForConditionalGeneration.from_pretrained(str(model_path))

        if self.device == "cuda":
            import torch

            if torch.cuda.is_available():
                self.model = self.model.to("cuda")
            else:
                print("Warning: CUDA not available, using CPU")
                self.device = "cpu"

    def _load_model_ctranslate2(self):
        """Load model using CTranslate2 backend."""
        try:
            import ctranslate2
            from transformers import AutoTokenizer
        except ImportError:
            raise ImportError(
                "ctranslate2 or transformers not installed. "
                "Install with: pip install ctranslate2 transformers"
            )

        model_path = (
            self.model_path
            / "ct2_models"
            / f"t5-{self.model_size}-ct2-{self.quantization}"
        )
        tokenizer_path = self.model_path / f"t5-{self.model_size}"

        if not model_path.exists():
            raise FileNotFoundError(f"CTranslate2 model not found at {model_path}")

        if not tokenizer_path.exists():
            raise FileNotFoundError(f"Tokenizer not found at {tokenizer_path}")

        self.model = ctranslate2.Translator(str(model_path), device=self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path))

    def _load_model(self):
        """Load the model based on backend."""
        if self.backend == "transformers":
            self._load_model_transformers()
        else:
            self._load_model_ctranslate2()

    def _decode_changelog(self, output):
        """Decode model output while preserving newlines."""
        if isinstance(output, list):
            # CTranslate2 output (tokens)
            decoded = self.tokenizer.decode(
                self.tokenizer.convert_tokens_to_ids(output), skip_special_tokens=False
            )
        else:
            # Transformers output (token IDs)
            decoded = self.tokenizer.decode(output, skip_special_tokens=False)

        # Remove special tokens
        decoded = decoded.replace(self.tokenizer.pad_token or "<pad>", "")
        decoded = decoded.replace(self.tokenizer.eos_token or "</s>", "")
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
        if self.backend == "transformers":
            return self._generate_transformers(input_text, beam_size)
        else:
            return self._generate_ctranslate2(input_text, beam_size)

    def _generate_transformers(self, input_text, beam_size):
        """Generate using transformers backend."""
        inputs = self.tokenizer(
            input_text, return_tensors="pt", max_length=1024, truncation=True
        )

        if self.device == "cuda":
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        outputs = self.model.generate(
            **inputs,
            max_length=512,
            num_beams=beam_size,
            no_repeat_ngram_size=4,
            early_stopping=True,
        )

        return self._decode_changelog(outputs[0])

    def _generate_ctranslate2(self, input_text, beam_size):
        """Generate using CTranslate2 backend."""
        input_tokens = self.tokenizer.convert_ids_to_tokens(
            self.tokenizer.encode(input_text, max_length=1024, truncation=True)
        )

        results = self.model.translate_batch(
            [input_tokens],
            beam_size=beam_size,
            max_decoding_length=512,
            no_repeat_ngram_size=4,
        )

        return self._decode_changelog(results[0].hypotheses[0])
