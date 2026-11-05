import os
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.company import Company
from app.models.user import AuthProvider, User, UserRole


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh, isolated database schema for each test."""
    test_db_url = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    if "sqlite" in test_db_url:
        engine = create_async_engine(
            test_db_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_async_engine(
            test_db_url,
            connect_args={"server_settings": {"search_path": "job_sentry,public"}},
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTP async test client with database dependency override."""
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def registered_user(db_session: AsyncSession) -> User:
    """Fixture providing an existing active recruiter user."""
    user = User(
        name="Alice Recruiter",
        email="alice@example.com",
        password_hash=hash_password("ValidPass123!"),
        role=UserRole.RECRUITER,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(registered_user: User) -> dict:
    """Fixture providing authorization header for the registered user."""
    token = create_access_token(
        subject=str(registered_user.id),
        role=registered_user.role.value,
        company_id=str(registered_user.company_id) if registered_user.company_id else None,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def company_with_admin(db_session: AsyncSession) -> tuple[Company, User]:
    """Fixture creating a company and its administrator user."""
    company = Company(
        name="Acme Corp",
        industry="Technology",
        website="https://acme.example.com",
        description="A great tech company",
        location="San Francisco, CA",
    )
    db_session.add(company)
    await db_session.flush()

    admin = User(
        name="Bob Admin",
        email="bob@acme.example.com",
        password_hash=hash_password("AdminPass123!"),
        role=UserRole.ADMIN,
        company_id=company.id,
        auth_provider=AuthProvider.EMAIL,
        is_active=True,
        is_verified=True,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(company)
    await db_session.refresh(admin)
    return company, admin


@pytest_asyncio.fixture
async def admin_headers(company_with_admin: tuple[Company, User]) -> dict:
    """Authorization headers for the company administrator."""
    company, admin = company_with_admin
    token = create_access_token(
        subject=str(admin.id),
        role=admin.role.value,
        company_id=str(company.id),
    )
    return {"Authorization": f"Bearer {token}"}
