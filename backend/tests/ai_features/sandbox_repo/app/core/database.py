from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


async def get_db():  # overridden in tests
    raise RuntimeError("stub")
    yield
