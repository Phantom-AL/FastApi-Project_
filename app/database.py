from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from sqlalchemy.orm import declarative_base

URL_DATABASE = "postgresql+asyncpg://FastAPI:123456@localhost:5432/FastAPI_Test"

engine = create_async_engine(URL_DATABASE, echo=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()
