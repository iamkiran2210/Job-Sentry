"""Importing this package registers every AI-feature table on Base.metadata (needed by Alembic)."""

from .application import Application
from app.modules.application_status.models import ApplicationStatusHistory
from .candidate import Candidate
from .extracted_profile import ExtractedProfile
from .identity_suggestion import IdentitySuggestion
from .resume import Resume

__all__ = [
    "Application",
    "ApplicationStatusHistory",
    "Candidate",
    "ExtractedProfile",
    "IdentitySuggestion",
    "Resume",
]
