import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text, select, func

from auth import engine, async_session
from db_init import run_startup_migrations
from models import Base, Movie
from routers import auth, oauth, users, movies, comments

SEED_MOVIES = [
    {
        "title": "The Shawshank Redemption",
        "year": 1994,
        "imdb_rating": "9.3",
        "imdb_id": "tt0111161",
        "duration_minutes": 142,
        "available_subtitles": "en,fr,es,de",
        "genres": "Drama",
        "description": "Two imprisoned men bond over a number of years, finding solace and eventual redemption through acts of common decency.",
    },
    {
        "title": "The Godfather",
        "year": 1972,
        "imdb_rating": "9.2",
        "imdb_id": "tt0068646",
        "duration_minutes": 175,
        "available_subtitles": "en,fr,es,it",
        "genres": "Crime, Drama",
        "description": "The aging patriarch of an organized crime dynasty transfers control of his clandestine empire to his reluctant son.",
    },
    {
        "title": "Pulp Fiction",
        "year": 1994,
        "imdb_rating": "8.9",
        "imdb_id": "tt0110912",
        "duration_minutes": 154,
        "available_subtitles": "en,fr,es",
        "genres": "Crime, Drama",
        "description": "The lives of two mob hitmen, a boxer, a gangster and his wife intertwine in four tales of violence and redemption.",
    },
    {
        "title": "Inception",
        "year": 2010,
        "imdb_rating": "8.8",
        "imdb_id": "tt1375666",
        "duration_minutes": 148,
        "available_subtitles": "en,fr,es,de,ja",
        "genres": "Action, Sci-Fi, Thriller",
        "description": "A thief who steals corporate secrets through the use of dream-sharing technology is given the inverse task of planting an idea.",
    },
    {
        "title": "Interstellar",
        "year": 2014,
        "imdb_rating": "8.7",
        "imdb_id": "tt0816692",
        "duration_minutes": 169,
        "available_subtitles": "en,fr,es,de",
        "genres": "Adventure, Drama, Sci-Fi",
        "description": "A team of explorers travel through a wormhole in space in an attempt to ensure humanity's survival.",
    },
]


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

    async with async_session() as session:
        result = await session.execute(select(func.count(Movie.id)))
        count = result.scalar()
        if count == 0:
            for m in SEED_MOVIES:
                session.add(Movie(**m))
            await session.commit()
            print(f"✅ Seeded {len(SEED_MOVIES)} sample movies.")

    yield


app = FastAPI(lifespan=lifespan, root_path="/api")

app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(users.router)
app.include_router(movies.router)
app.include_router(comments.router)
