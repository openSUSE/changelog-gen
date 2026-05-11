"""
AI-powered changelog generator using fine-tuned T5 models.

This package provides tools to generate human-readable changelog entries
from code changes using fine-tuned T5 models. It integrates with both
osc (Open Build Service) and git workflows.
"""

__version__ = "0.1.0"
__author__ = "Christian Goll"
__email__ = "Christian.Goll@gmail.com"
__license__ = "Apache-2.0"

from .model import ChangelogGenerator

__all__ = ["ChangelogGenerator"]
