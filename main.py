from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from fastapi.openapi.docs import get_swagger_ui_html
from typing import Annotated, List
from pydantic import BaseModel
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from enum import Enum
import jwt
import secrets
import os
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import psycopg2
from psycopg2.extras import RealDictCursor
from database import get_db_connection, init_db
from todos import router as todos_router

load_dotenv()

# Config
MODE = os.getenv("MODE", "DEV").upper()
DOCS_USER = os.getenv("DOCS_USER", "admin")
DOCS_PASSWORD = os.getenv("DOCS_PASSWORD", "docs123")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

if MODE not in ["DEV", "PROD"]:
    raise ValueError(f"Invalid MODE: {MODE}")

init_db()

# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="FastAPI Auth + RBAC + Todo CRUD", docs_url=None, redoc_url=None,
              openapi_url=None if MODE == "PROD" else "/openapi.json")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(todos_router)

# Security
basic_security = HTTPBasic()
bearer_security = HTTPBearer(auto_error=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
token_blacklist = set()

class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"

# Pydantic models
class UserRegister(BaseModel):
    username: str
    password: str
    role: UserRole = UserRole.USER

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_role: str

# Database helpers
def get_user_from_db(username: str):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, username, password, role FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def create_user_in_db(username: str, hashed_password: str, role: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s) RETURNING id",
                (username, hashed_password, role))
    user_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return user_id

def get_all_users_from_db():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, username, role FROM users ORDER BY id")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return users

def delete_user_from_db(username: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE username = %s RETURNING id", (username,))
    deleted = cur.fetchone() is not None
    conn.commit()
    cur.close()
    conn.close()
    return deleted

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role")
        if not username or not role or token in token_blacklist:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username, role
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except:
        raise HTTPException(status_code=401, detail="Invalid token")

# Dependencies
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username, role = verify_access_token(credentials.credentials)
    return {"username": username, "role": role}

def require_role(allowed_roles: List[UserRole]):
    async def checker(current_user = Depends(get_current_user)):
        if current_user["role"] not in [r.value for r in allowed_roles]:
            raise HTTPException(status_code=403, detail="Forbidden")
        return current_user
    return checker

require_admin = require_role([UserRole.ADMIN])
require_user_or_admin = require_role([UserRole.ADMIN, UserRole.USER])
require_any_auth = require_role([UserRole.ADMIN, UserRole.USER, UserRole.GUEST])

# Docs auth
def auth_docs(creds: Annotated[HTTPBasicCredentials, Depends(basic_security)]):
    if not (secrets.compare_digest(creds.username, DOCS_USER) and 
            secrets.compare_digest(creds.password, DOCS_PASSWORD)):
        raise HTTPException(status_code=401, detail="Unauthorized", 
                           headers={"WWW-Authenticate": "Basic"})
    return True

if MODE == "DEV":
    @app.get("/docs", include_in_schema=False, dependencies=[Depends(auth_docs)])
    async def docs():
        return get_swagger_ui_html(openapi_url="/openapi.json", title="API Docs")
    
    @app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(auth_docs)])
    async def openapi():
        from fastapi.openapi.utils import get_openapi
        return get_openapi(title=app.title, version="1.0.0", routes=app.routes)

# Endpoints
@app.post("/register", status_code=201)
@limiter.limit("1/minute")
async def register(request: Request, user: UserRegister):
    if get_user_from_db(user.username):
        raise HTTPException(status_code=409, detail="User already exists")
    hashed = hash_password(user.password)
    create_user_in_db(user.username, hashed, user.role.value)
    return {"message": "User registered successfully!", "role": user.role.value}

@app.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, login: LoginRequest):
    user = get_user_from_db(login.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(login.password, user["password"]):
        raise HTTPException(status_code=401, detail="Authorization failed")
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return TokenResponse(access_token=token, user_role=user["role"])

@app.get("/protected_resource")
async def protected(current_user = Depends(require_any_auth)):
    return {"message": "Access granted", "user": current_user["username"], "role": current_user["role"]}

@app.get("/admin/users")
async def admin_users(current_user = Depends(require_admin)):
    return get_all_users_from_db()

@app.delete("/admin/users/{username}")
async def admin_delete_user(username: str, current_user = Depends(require_admin)):
    if username == current_user["username"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if not delete_user_from_db(username):
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": f"User '{username}' deleted"}

@app.post("/logout")
async def logout(creds: HTTPAuthorizationCredentials = Depends(bearer_security)):
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_blacklist.add(creds.credentials)
    return {"message": "Logged out"}

@app.get("/health")
async def health():
    return {"status": "healthy", "mode": MODE}