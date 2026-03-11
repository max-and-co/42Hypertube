from fastapi import FastAPI, Depends, Request
from contextlib import asynccontextmanager
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Import our new auth dependency
from auth import get_current_user_from_cookie

DATABASE_URL = os.getenv("DATABASE_URL")

@asynccontextmanager
async def lifespan(app: FastAPI):
    retries = 10
    while retries > 0:
        try:
            print(f"Connecting to DB... ({retries} retries left)")
            engine = create_async_engine(DATABASE_URL)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print("✅ Database connected successfully.")
            break
        except Exception as e:
            print(f"❌ Database not ready yet: {e}")
            retries -= 1
            await asyncio.sleep(2)
    
    yield

app = FastAPI(lifespan=lifespan, root_path="/api/torrent")

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "torrent-service"}

@app.get("/protected")
async def protected_route(user_id: int = Depends(get_current_user_from_cookie)):
    return {
        "message": "You have successfully accessed a protected route on the torrent-service!",
        "user_id": user_id
    }
