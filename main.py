from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import timedelta
from sqlalchemy.orm import Session

from database import engine, get_db, Base
from models import TaskModel, UserModel
from auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_password_hash,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

# Creates all tables in the database automatically on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Task Manager API",
    description="A clean REST API for managing tasks",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------
# PYDANTIC MODELS (request/response shapes)
# ----------------------------

class Task(BaseModel):
    title: str = Field(..., min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=300)
    done: bool = Field(default=False)
    priority: Optional[str] = Field(default="medium")
    due_date: Optional[str] = Field(None, description="Due date in YYYY-MM-DD format")

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value):
        if value.strip() == "":
            raise ValueError("Title cannot be blank")
        return value.strip()

    @field_validator("priority")
    @classmethod
    def priority_must_be_valid(cls, value):
        allowed = ["low", "medium", "high"]
        if value not in allowed:
            raise ValueError(f"Priority must be one of: {allowed}")
        return value

    @field_validator("due_date")
    @classmethod
    def due_date_must_be_valid(cls, value):
        if value is None:
            return value
        try:
            from datetime import datetime
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            raise ValueError("Due date must be in YYYY-MM-DD format")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=2)
    email: str


# ----------------------------
# HELPER
# ----------------------------

def find_task(task_id: int, db: Session):
    task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


# ----------------------------
# AUTH ROUTES
# ----------------------------

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Task API is running", "version": "1.0.0"}


@app.post("/auth/register", status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    # Check username not already taken
    if db.query(UserModel).filter(UserModel.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    # Check email not already taken
    if db.query(UserModel).filter(UserModel.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = UserModel(
        username=data.username,
        full_name=data.full_name,
        email=data.email,
        hashed_password=get_password_hash(data.password)
    )
    db.add(new_user)        # stage the new user
    db.commit()             # save to database
    db.refresh(new_user)    # get the saved data back
    return {"message": f"User {data.username} registered successfully"}


@app.post("/auth/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/auth/me")
def get_me(current_user=Depends(get_current_user)):
    return {
        "username": current_user.username,
        "full_name": current_user.full_name,
        "email": current_user.email,
    }


# ----------------------------
# TASK ROUTES (PROTECTED)
# ----------------------------

@app.get("/tasks")
def get_tasks(
    done: Optional[bool] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(TaskModel).filter(TaskModel.owner == current_user.username)
    if done is not None:
        query = query.filter(TaskModel.done == done)
    tasks = query.all()
    return {"tasks": tasks, "count": len(tasks)}


@app.get("/tasks/{task_id}")
def get_task(
    task_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = find_task(task_id, db)
    if task.owner != current_user.username:
        raise HTTPException(status_code=403, detail="Not authorized to view this task")
    return task


@app.post("/tasks", status_code=201)
def create_task(
    task: Task,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from datetime import date
    due = None
    if task.due_date:
        due = date.fromisoformat(task.due_date)

    new_task = TaskModel(
        title=task.title,
        description=task.description,
        done=task.done,
        priority=task.priority,
        owner=current_user.username,
        due_date=due
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return new_task


@app.put("/tasks/{task_id}")
def update_task(
    task_id: int,
    updated: Task,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from datetime import date
    task = find_task(task_id, db)
    if task.owner != current_user.username:
        raise HTTPException(status_code=403, detail="Not authorized to update this task")
    task.title       = updated.title
    task.description = updated.description
    task.done        = updated.done
    task.priority    = updated.priority
    task.due_date    = date.fromisoformat(updated.due_date) if updated.due_date else None
    db.commit()
    db.refresh(task)
    return task


@app.patch("/tasks/{task_id}/done")
def mark_task_done(
    task_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = find_task(task_id, db)
    if task.owner != current_user.username:
        raise HTTPException(status_code=403, detail="Not authorized")
    task.done = True
    db.commit()
    db.refresh(task)
    return {"message": f"Task {task_id} marked as done", "task": task}


@app.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = find_task(task_id, db)
    if task.owner != current_user.username:
        raise HTTPException(status_code=403, detail="Not authorized to delete this task")
    db.delete(task)
    db.commit()
    return {"message": f"Task {task_id} deleted successfully"}