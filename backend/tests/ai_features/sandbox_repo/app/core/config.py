import os


class _Settings:
    SANDBOX = True
    DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test_resumes.db")
    API_V1_STR = "/api/v1"


settings = _Settings()
