from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import drafts, courses
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Course AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(drafts.router)
app.include_router(courses.router)
