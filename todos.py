from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
import psycopg2
from psycopg2.extras import RealDictCursor
from database import get_db_connection
from models import TodoCreate, TodoUpdate, TodoResponse

router = APIRouter(prefix="/todos", tags=["Todos"])

async def get_current_user(credentials = Depends()):
    # This will be injected from main.py
    pass

def require_user_or_admin(current_user):
    if current_user["role"] not in ["admin", "user"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    return current_user

@router.post("/", response_model=TodoResponse, status_code=201)
async def create_todo(todo: TodoCreate, current_user: dict = Depends(require_user_or_admin)):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        INSERT INTO todos (title, description, completed, created_by)
        VALUES (%s, %s, %s, %s)
        RETURNING id, title, description, completed, created_by, created_at, updated_at
    """, (todo.title, todo.description, False, current_user["username"]))
    
    new_todo = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return TodoResponse(**new_todo)

@router.get("/{todo_id}", response_model=TodoResponse)
async def get_todo(todo_id: int, current_user: dict = Depends(require_user_or_admin)):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if current_user["role"] == "admin":
        cur.execute("SELECT * FROM todos WHERE id = %s", (todo_id,))
    else:
        cur.execute("SELECT * FROM todos WHERE id = %s AND created_by = %s", (todo_id, current_user["username"]))
    
    todo = cur.fetchone()
    cur.close()
    conn.close()
    
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return TodoResponse(**todo)

@router.get("/", response_model=List[TodoResponse])
async def get_all_todos(current_user: dict = Depends(require_user_or_admin), skip: int = 0, limit: int = 100):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if current_user["role"] == "admin":
        cur.execute("SELECT * FROM todos ORDER BY id LIMIT %s OFFSET %s", (limit, skip))
    else:
        cur.execute("SELECT * FROM todos WHERE created_by = %s ORDER BY id LIMIT %s OFFSET %s", 
                   (current_user["username"], limit, skip))
    
    todos = cur.fetchall()
    cur.close()
    conn.close()
    return [TodoResponse(**todo) for todo in todos]

@router.put("/{todo_id}", response_model=TodoResponse)
async def update_todo(todo_id: int, todo_update: TodoUpdate, current_user: dict = Depends(require_user_or_admin)):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Check permission
    if current_user["role"] == "admin":
        cur.execute("SELECT * FROM todos WHERE id = %s", (todo_id,))
    else:
        cur.execute("SELECT * FROM todos WHERE id = %s AND created_by = %s", (todo_id, current_user["username"]))
    
    existing = cur.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Todo not found")
    
    # Build update query
    updates = []
    values = []
    if todo_update.title is not None:
        updates.append("title = %s")
        values.append(todo_update.title)
    if todo_update.description is not None:
        updates.append("description = %s")
        values.append(todo_update.description)
    if todo_update.completed is not None:
        updates.append("completed = %s")
        values.append(todo_update.completed)
    
    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        query = f"UPDATE todos SET {', '.join(updates)} WHERE id = %s RETURNING *"
        values.append(todo_id)
        cur.execute(query, values)
        updated = cur.fetchone()
        conn.commit()
    else:
        updated = existing
    
    cur.close()
    conn.close()
    return TodoResponse(**updated)

@router.delete("/{todo_id}")
async def delete_todo(todo_id: int, current_user: dict = Depends(require_user_or_admin)):
    conn = get_db_connection()
    cur = conn.cursor()
    
    if current_user["role"] == "admin":
        cur.execute("DELETE FROM todos WHERE id = %s RETURNING id", (todo_id,))
    else:
        cur.execute("DELETE FROM todos WHERE id = %s AND created_by = %s RETURNING id", 
                   (todo_id, current_user["username"]))
    
    deleted = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"message": "Todo deleted successfully", "id": todo_id}