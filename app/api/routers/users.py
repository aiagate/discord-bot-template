from fastapi import APIRouter, HTTPException
from flow_res import Err
from pydantic import BaseModel

from app.core.mediator import Mediator
from app.usecases.users.create_user import CreateUserCommand
from app.usecases.users.get_user import GetUserQuery

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(BaseModel):
    display_name: str
    email: str


class CreateUserResponse(BaseModel):
    id: str


class UserResponse(BaseModel):
    id: str
    display_name: str
    email: str


@router.post("", response_model=CreateUserResponse)
async def create_user(request: CreateUserRequest) -> CreateUserResponse:
    """Create a new user."""
    command = CreateUserCommand(display_name=request.display_name, email=request.email)

    result = await Mediator.send_async(command)

    if isinstance(result, Err):
        raise HTTPException(status_code=400, detail=result.error.message)

    user_id = result.unwrap().id
    return CreateUserResponse(id=user_id)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str) -> UserResponse:
    """Get a user by ID."""
    query = GetUserQuery(user_id=user_id)
    result = await Mediator.send_async(query)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=result.error.message)

    user_result = result.unwrap()

    return UserResponse(
        id=user_result.id,
        display_name=user_result.display_name,
        email=user_result.email,
    )
