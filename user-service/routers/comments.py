from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_id
from database import get_db
from models import Comment, Movie, User
from schemas import CommentCreate, CommentUpdate

router = APIRouter()


@router.get("/comments")
async def list_comments(request: Request, db: AsyncSession = Depends(get_db)):
    """GET /api/comments — latest 50 comments with author info (authenticated)."""
    get_current_user_id(request)
    stmt = (
        select(Comment, User.username.label("author_username"))
        .join(User, User.id == Comment.author_id)
        .order_by(Comment.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": row.Comment.id,
            "content": row.Comment.content,
            "author_username": row.author_username,
            "movie_id": row.Comment.movie_id,
            "created_at": row.Comment.created_at,
        }
        for row in rows
    ]


@router.get("/comments/{comment_id:int}")
async def get_comment(comment_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """GET /api/comments/:id — single comment with author info (authenticated)."""
    get_current_user_id(request)
    stmt = (
        select(Comment, User.username.label("author_username"))
        .join(User, User.id == Comment.author_id)
        .where(Comment.id == comment_id)
    )
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Comment not found")
    return {
        "id": row.Comment.id,
        "content": row.Comment.content,
        "author_username": row.author_username,
        "movie_id": row.Comment.movie_id,
        "created_at": row.Comment.created_at,
    }


@router.patch("/comments/{comment_id:int}")
async def update_comment(
    comment_id: int,
    request: Request,
    data: CommentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """PATCH /api/comments/:id — update comment content (authenticated)."""
    get_current_user_id(request)
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalars().first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if data.comment is not None:
        comment.content = data.comment
    await db.commit()
    await db.refresh(comment)
    return {"id": comment.id, "content": comment.content}


@router.delete("/comments/{comment_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """DELETE /api/comments/:id — delete a comment (authenticated)."""
    get_current_user_id(request)
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalars().first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    await db.delete(comment)
    await db.commit()


@router.post("/comments", status_code=status.HTTP_201_CREATED)
async def create_comment(
    request: Request,
    data: CommentCreate,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/comments — create a comment (authenticated). Body: comment + movie_id."""
    author_id = get_current_user_id(request)

    if data.movie_id is None:
        raise HTTPException(status_code=400, detail="movie_id is required")

    result = await db.execute(select(Movie).where(Movie.id == data.movie_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Movie not found")

    comment = Comment(content=data.comment, movie_id=data.movie_id, author_id=author_id)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return {
        "id": comment.id,
        "content": comment.content,
        "movie_id": comment.movie_id,
        "created_at": comment.created_at,
    }
