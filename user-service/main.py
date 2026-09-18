import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from auth import engine
from db_init import run_startup_migrations
from models import Base
from routers import auth, oauth, users, movies, comments


@asynccontextmanager
async def lifespan(app: FastAPI):
    retries = 10
    while retries > 0:
        try:
            print(f"Connecting to DB... ({retries} retries left)")
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await run_startup_migrations(conn)
            print("✅ Database connected & tables created successfully.")
            break
        except Exception as e:
            print(f"❌ Database not ready yet: {e}")
            retries -= 1
            await asyncio.sleep(2)
    else:
        print("❌ Could not connect to database after retries.")
        yield
        return

    yield


app = FastAPI(lifespan=lifespan, root_path="/api")

app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(users.router)
app.include_router(movies.router)
app.include_router(comments.router)
