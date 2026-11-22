from importlib import import_module
from typing import Protocol

from app.core.config import settings
from app.core.exceptions import AppException


class RequirementExtractionProvider(Protocol):
    async def extract_requirements(self, description: str) -> object:
        """Return structured requirement suggestions for recruiter review."""


def get_requirement_extraction_provider() -> RequirementExtractionProvider | None:
    if not settings.AI_REQUIREMENTS_PROVIDER:
        return None
    try:
        module_path, factory_name = settings.AI_REQUIREMENTS_PROVIDER.split(":", 1)
        factory = getattr(import_module(module_path), factory_name)
        return factory()

    except (ImportError, AttributeError, ValueError) as exc:
        raise AppException(
            "Configured requirement extraction provider could not be loaded",
            status_code=503,
        ) from exc
