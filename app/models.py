from pydantic import BaseModel
from typing import List, Optional

class TestItem(BaseModel):
    question: str
    options: List[str]
    answer: str
    solution: str

class Lesson(BaseModel):
    lessonTitle: str
    theory: str
    tests: List[TestItem]

class Topic(BaseModel):
    topicTitle: str
    lessons: List[Lesson]

class Module(BaseModel):
    moduleNumber: int
    moduleTitle: str
    weeks: List[int]
    topics: List[Topic]

class CourseDraftRequest(BaseModel):
    courseTitle: str
    level: str
    durationWeeks: int
    description: str

class CourseDraftUpdateRequest(BaseModel):
    courseTitle: Optional[str] = None
    level: Optional[str] = None
    durationWeeks: Optional[int] = None
    description: Optional[str] = None
    modules: Optional[List[Module]] = None

class PublishDraftRequest(BaseModel):
    thumbnail: Optional[str] = None
