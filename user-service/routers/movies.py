from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_id
from database import get_db
from models import Movie, Comment
from schemas import CommentCreate

router = APIRouter()


@router.get("/movies")
async def list_movies(db: AsyncSession = Depends(get_db)):
    """GET /api/movies — public frontpage movies list."""
    result = await db.execute(select(Movie).order_by(Movie.imdb_rating.desc()))
    movies = result.scalars().all()
    return [{"id": m.id, "title": m.title} for m in movies]


@router.get("/movies/{movie_id:int}")
async def get_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    """GET /api/movies/:id — full movie info, public."""
    result = await db.execute(select(Movie).where(Movie.id == movie_id))
    movie = result.scalars().first()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    count_result = await db.execute(
        select(func.count(Comment.id)).where(Comment.movie_id == movie_id)
    )
    comment_count = count_result.scalar()

    return {
        "id": movie.id,
        "title": movie.title,
        "year": movie.year,
        "imdb_rating": movie.imdb_rating,
        "imdb_id": movie.imdb_id,
        "duration_minutes": movie.duration_minutes,
        "available_subtitles": movie.available_subtitles.split(",") if movie.available_subtitles else [],
        "genres": movie.genres,
        "thumbnail": movie.thumbnail,
        "description": movie.description,
        "comment_count": comment_count,
    }


@router.post("/movies/{movie_id:int}/comments", status_code=status.HTTP_201_CREATED)
async def create_comment_for_movie(
    movie_id: int,
    request: Request,
    data: CommentCreate,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/movies/:movie_id/comments — create a comment (authenticated)."""
    author_id = get_current_user_id(request)

    result = await db.execute(select(Movie).where(Movie.id == movie_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Movie not found")

    comment = Comment(content=data.comment, movie_id=movie_id, author_id=author_id)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return {
        "id": comment.id,
        "content": comment.content,
        "movie_id": comment.movie_id,
        "created_at": comment.created_at,
    }
