"""Processing pipeline and pluggable EEG processors."""

from .base import EEGProcessor
from .pipeline import Pipeline
from .registry import PROCESSORS, create_processor

__all__ = ["EEGProcessor", "Pipeline", "PROCESSORS", "create_processor"]
