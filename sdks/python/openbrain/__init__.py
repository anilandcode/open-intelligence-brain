"""Open Intelligence Brain Python SDK."""

from .cli import main as cli_main
from .client import Brain, BrainError

__version__ = "2.4.0"
__all__ = ["Brain", "BrainError", "cli_main"]
