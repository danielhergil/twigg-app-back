from fastapi import APIRouter, HTTPException
from ..firebase_client import db

router = APIRouter(tags=["courses"])

@router.get("/courses/{course_id}")
def get_course_full(course_id: str):
    course_ref = db.collection("courses").document(course_id)
    course_doc = course_ref.get()
    if not course_doc.exists:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    course = course_doc.to_dict()
    course["id"] = course_id

    modules_snap = course_ref.collection("modules").stream()
    modules = []
    for m in modules_snap:
        mdata = m.to_dict()
        mdata["id"] = m.id
        topics_list = []
        for t in course_ref.collection("modules").document(m.id).collection("topics").stream():
            tdata = t.to_dict()
            tdata["id"] = t.id
            lessons_list = []
            for l in course_ref.collection("modules").document(m.id).collection("topics").document(t.id).collection("lessons").stream():
                ldata = l.to_dict()
                ldata["id"] = l.id
                lessons_list.append(ldata)
            tdata["lessons"] = lessons_list
            topics_list.append(tdata)
        mdata["topics"] = topics_list
        modules.append(mdata)
    course["modules"] = modules
    return {"course": course}
