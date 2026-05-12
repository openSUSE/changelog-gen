from changelog_ai.model import ChangelogGenerator
import sys

def main():
    # Initialize generator (defaults to large model)
    # Note: You might need to provide a model_path if not in default location
    try:
        generator = ChangelogGenerator(model_size="base", device="cpu")
    except Exception as e:
        print(f"Error loading model: {e}")
        print("Please ensure the model is downloaded and path is correct in model.py")
        return

    # Example diff (usually you'd read this from a file or git)
    diff = """
diff --git a/changelog_ai/model.py b/changelog_ai/model.py
index 1234567..89abcde 100644
--- a/changelog_ai/model.py
+++ b/changelog_ai/model.py
@@ -10,1 +10,1 @@
-    import sentencepiece as spm
+    from tokenizers import Tokenizer
    """

    print("Generating changelog...")
    changelog = generator.generate(diff)
    print("\nGenerated Changelog:")
    print("-" * 20)
    print(changelog)
    print("-" * 20)

if __name__ == "__main__":
    main()
