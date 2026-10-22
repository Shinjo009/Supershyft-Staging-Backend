"""Author blog dashboard routes."""



from __future__ import annotations



from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from sqlalchemy.ext.asyncio import AsyncSession



from common.responses import success_response

from db.session import get_db

from modules.blog.dependencies import BlogActor, get_current_author, get_optional_author

from modules.blog.errors import ApiError

from modules.blog.schemas import CategoryWrite, PostWrite

from modules.blog.service import BlogService



router = APIRouter(prefix="/blog", tags=["blog"])





def get_blog_service() -> BlogService:

    return BlogService()





@router.get("/posts")

async def list_posts(

    status_filter: str = Query(default="all", alias="status"),

    category: str = Query(default=""),

    search: str = Query(default=""),

    page: int = Query(default=1, ge=1),

    limit: int = Query(default=20, ge=1, le=50),

    db: AsyncSession = Depends(get_db),

    author: BlogActor | None = Depends(get_optional_author),

    service: BlogService = Depends(get_blog_service),

):

    data = await service.list_posts(

        db,

        status=status_filter,

        category=category,

        search=search,

        page=page,

        limit=limit,

        public_only=author is None,

    )

    return success_response(data)





@router.post("/posts", status_code=status.HTTP_201_CREATED)

async def create_post(

    body: PostWrite,

    db: AsyncSession = Depends(get_db),

    author: BlogActor = Depends(get_current_author),

    service: BlogService = Depends(get_blog_service),

):

    data = await service.create_post(db, body, author)

    await db.commit()

    return success_response(data)





@router.get("/posts/{post_id}")

async def get_post(

    post_id: int,

    db: AsyncSession = Depends(get_db),

    author: BlogActor | None = Depends(get_optional_author),

    service: BlogService = Depends(get_blog_service),

):

    return success_response(await service.get_post(db, post_id, public_only=author is None))





@router.put("/posts/{post_id}")

async def update_post(

    post_id: int,

    body: PostWrite,

    db: AsyncSession = Depends(get_db),

    author: BlogActor = Depends(get_current_author),

    service: BlogService = Depends(get_blog_service),

):

    data = await service.update_post(db, post_id, body, author)

    await db.commit()

    return success_response(data)





@router.delete("/posts/{post_id}")

async def delete_post(

    post_id: int,

    db: AsyncSession = Depends(get_db),

    author: BlogActor = Depends(get_current_author),

    service: BlogService = Depends(get_blog_service),

):

    data = await service.delete_post(db, post_id, author)

    await db.commit()

    return success_response(data)





@router.get("/categories")

async def list_categories(

    db: AsyncSession = Depends(get_db),

    _: BlogActor = Depends(get_current_author),

    service: BlogService = Depends(get_blog_service),

):

    return success_response(await service.list_categories(db))





@router.post("/categories", status_code=status.HTTP_201_CREATED)

async def create_category(

    body: CategoryWrite,

    db: AsyncSession = Depends(get_db),

    _: BlogActor = Depends(get_current_author),

    service: BlogService = Depends(get_blog_service),

):

    data = await service.create_category(db, body)

    await db.commit()

    return success_response(data)





@router.put("/categories/{category_id}")

async def update_category(

    category_id: int,

    body: CategoryWrite,

    db: AsyncSession = Depends(get_db),

    _: BlogActor = Depends(get_current_author),

    service: BlogService = Depends(get_blog_service),

):

    data = await service.update_category(db, category_id, body)

    await db.commit()

    return success_response(data)





@router.delete("/categories/{category_id}")

async def delete_category(

    category_id: int,

    db: AsyncSession = Depends(get_db),

    _: BlogActor = Depends(get_current_author),

    service: BlogService = Depends(get_blog_service),

):

    data = await service.delete_category(db, category_id)

    await db.commit()

    return success_response(data)





@router.post("/uploads")

async def upload_media(

    file: UploadFile | None = File(None),

    image: UploadFile | None = File(None),

    _: BlogActor = Depends(get_current_author),

    service: BlogService = Depends(get_blog_service),

):

    upload = file or image

    if upload is None:

        raise ApiError("No file uploaded")

    url = await service.save_upload(upload)

    return success_response({"url": url})

