from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.mediator import Mediator
from app.core.result import is_err
from app.usecases.teams.create_team import CreateTeamCommand
from app.usecases.teams.get_team import GetTeamQuery
from app.usecases.teams.update_team import UpdateTeamCommand

router = APIRouter(prefix="/teams", tags=["teams"])


class CreateTeamRequest(BaseModel):
    name: str


class CreateTeamResponse(BaseModel):
    id: str


class TeamResponse(BaseModel):
    id: str
    name: str
    version: int


class UpdateTeamRequest(BaseModel):
    name: str


@router.post("", response_model=CreateTeamResponse)
async def create_team(request: CreateTeamRequest) -> CreateTeamResponse:
    """Create a new team."""
    command = CreateTeamCommand(name=request.name)

    # Mediator returns a ResultAwaitable, which we await to get the Result
    result = await Mediator.send_async(command)

    if is_err(result):
        # In a real app, you would map ErrorType to status codes
        raise HTTPException(status_code=400, detail=result.error.message)

    team_id = result.unwrap().id
    return CreateTeamResponse(id=team_id)


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(team_id: str) -> TeamResponse:
    """Get a team by ID."""
    query = GetTeamQuery(id=team_id)
    result = await Mediator.send_async(query)

    if is_err(result):
        raise HTTPException(status_code=404, detail=result.error.message)

    team_result = result.unwrap()

    return TeamResponse(
        id=team_result.id,
        name=team_result.name,
        version=team_result.version,
    )


@router.put("/{team_id}", response_model=CreateTeamResponse)
async def update_team(team_id: str, request: UpdateTeamRequest) -> CreateTeamResponse:
    """Update a team's name."""
    command = UpdateTeamCommand(team_id=team_id, new_name=request.name)
    result = await Mediator.send_async(command)

    if is_err(result):
        raise HTTPException(status_code=400, detail=result.error.message)

    updated_team_id = result.unwrap().id
    return CreateTeamResponse(id=updated_team_id)
