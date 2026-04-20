from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("REMNA_MOCK_MODE", "true")
os.environ.setdefault("YOOKASSA_TEST_MODE", "true")
os.environ.setdefault("CRYPTOCLOUD_TEST_MODE", "true")
os.environ.setdefault("ADMIN_EMAILS", "admin@example.com")

from app.api.deps import get_email_service, get_remnawave_client  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402
from tests.fakes import FakeEmailService, FakeRemnawaveClient  # noqa: E402


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def fake_email() -> FakeEmailService:
    return FakeEmailService()


@pytest.fixture
def fake_remna() -> FakeRemnawaveClient:
    return FakeRemnawaveClient()


@pytest.fixture
async def client(
    db_session: AsyncSession,
    fake_email: FakeEmailService,
    fake_remna: FakeRemnawaveClient,
) -> AsyncIterator[AsyncClient]:
    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_email_service] = lambda: fake_email
    app.dependency_overrides[get_remnawave_client] = lambda: fake_remna

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
        yield test_client

    app.dependency_overrides.clear()
