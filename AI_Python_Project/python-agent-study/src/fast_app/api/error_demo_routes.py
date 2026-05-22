from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/error-demo", tags=["error-demo"])


@router.get("/bad-request")
def bad_request_demo() -> dict[str, str]:
    raise HTTPException(
        status_code=400,
        detail="这是一个 400 Bad Request 示例",
    )


@router.get("/not-found")
def not_found_demo() -> dict[str, str]:
    raise HTTPException(
        status_code=404,
        detail="这是一个 404 Not Found 示例",
    )