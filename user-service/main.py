from fastapi import FastAPI, Depends, Response, HTTPException, Request, status
from contextlib import asynccontextmanager
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, select
from pydantic import BaseModel, EmailStr

# Our local modules
from models import Base, User
from auth import get_password_hash, verify_password, create_access_token, get_current_user_from_cookie

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Retry DB connection until ready
    retries = 10
    while retries > 0:
        try:
            print(f"Connecting to DB... ({retries} retries left)")
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            
            # Create tables
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            print("✅ Database connected & tables created successfully.")
            break
        except Exception as e:
            print(f"❌ Database not ready yet: {e}")
            retries -= 1
            await asyncio.sleep(2)
    else:
        print("❌ Could not connect to database after retries.")
    
    yield
    # Shutdown logic (if any)

app = FastAPI(lifespan=lifespan, root_path="/api/users")

# DB Dependency
async def get_db():
    async with async_session() as session:
        yield session

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

@app.post("/register")
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check if user exists
    result = await db.execute(select(User).where(User.email == user.email))
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    new_user = User(email=user.email, hashed_password=hashed_password)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return {"message": "User registered successfully"}

@app.post("/login")
async def login(response: Response, user: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == user.email))
    db_user = result.scalars().first()
    
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": str(db_user.id)})
    
    # Set HttpOnly Cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=60 * 24 * 7 * 60, # 1 week in seconds
        expires=60 * 24 * 7 * 60,
        samesite="lax",
        secure=False  # Set to True in production with HTTPS
    )
    return {"message": "Login successful"}

@app.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out successfully"}

@app.get("/me")
async def read_users_me(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_current_user_from_cookie(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"email": user.email, "id": user.id}

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "user-service"}
