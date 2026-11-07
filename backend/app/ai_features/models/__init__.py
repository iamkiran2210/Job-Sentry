"""Importing this package registers every AI-feature table on Base.metadata (needed by Alembic)."""

from .application import Application
from .candidate import Candidate
from .extracted_profile import ExtractedProfile
from .identity_suggestion import IdentitySuggestion
from .resume import Resume

__all__ = [
    "Application",
    "Candidate",
    "ExtractedProfile",
    "IdentitySuggestion",
    "Resume",
]
