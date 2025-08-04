from fastapi import APIRouter, Depends, HTTPException, Path, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import Any
from ..models import CourseDraftRequest, CourseDraftUpdateRequest, PublishDraftRequest
from ..dependencies import get_current_user
from ..firebase_client import db
from ..ai_generator import generate_outline, expand_module
from datetime import datetime
import uuid
import json
from ..utils import slugify

router = APIRouter(tags=["drafts"])


async def expand_and_persist_full_draft(
    draft_id: str,
    request: CourseDraftRequest,
    uid: str,
):
    draft_ref = db.collection("drafts").document(draft_id)
    try:
        # 1. Obtener outline básico
        outline = await generate_outline(
            course_title=request.courseTitle,
            level=request.level,
            duration_weeks=request.durationWeeks,
            description=request.description,
        )
        expanded_modules = []
        for module in outline.get("modules", []):
            expanded = await expand_module(
                request.courseTitle,
                request.level,
                request.durationWeeks,
                request.description,
                module,
            )
            expanded_modules.append(expanded)
            # Actualizar parcialmente tras cada módulo
            partial_modules = expanded_modules + outline.get("modules", [])[len(expanded_modules):]
            draft_ref.update({
                "modules": partial_modules,
                "updatedAt": datetime.utcnow(),
            })

        # Guardar versión final
        draft_ref.update({
            "modules": expanded_modules,
            "status": "draft",
            "updatedAt": datetime.utcnow(),
        })
    except Exception as e:
        draft_ref.update({
            "status": "error",
            "errorMessage": str(e),
            "updatedAt": datetime.utcnow(),
        })
        print("[expand_and_persist_full_draft] error:", e)


@router.post("/generate-draft")
async def generate_draft(
    request: CourseDraftRequest,
    background_tasks: BackgroundTasks,
    auth_data: dict = Depends(get_current_user),
):
    uid = auth_data["uid"]
    draft_id = str(uuid.uuid4())
    draft_ref = db.collection("drafts").document(draft_id)

    # Generar outline inicial
    outline = await generate_outline(
        course_title=request.courseTitle,
        level=request.level,
        duration_weeks=request.durationWeeks,
        description=request.description,
    )
    initial_modules = outline.get("modules", [])

    # Crear draft inicial en estado "generating"
    draft_ref.set({
        "courseTitle": request.courseTitle,
        "level": request.level,
        "durationWeeks": request.durationWeeks,
        "description": request.description,
        "modules": initial_modules,
        "createdBy": uid,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
        "status": "generating",
    })

    # Lanzar expansión en background
    background_tasks.add_task(
        expand_and_persist_full_draft,
        draft_id,
        request,
        uid,
    )

    return {
        "draftId": draft_id,
        "draft": {
            "id": draft_id,
            "courseTitle": request.courseTitle,
            "level": request.level,
            "durationWeeks": request.durationWeeks,
            "description": request.description,
            "modules": initial_modules,
            "createdBy": uid,
            "status": "generating",
        },
    }


# Streaming por módulos (SSE) con persistencia incremental
@router.post("/generate-draft-stream")
async def generate_draft_stream(
    request: CourseDraftRequest,
    auth_data: dict = Depends(get_current_user),
):
    uid = auth_data["uid"]

    async def event_generator():
        draft_id = str(uuid.uuid4())
        draft_ref = db.collection("drafts").document(draft_id)
        try:
            # 1. Obtener outline básico
            outline = await generate_outline(
                course_title=request.courseTitle,
                level=request.level,
                duration_weeks=request.durationWeeks,
                description=request.description,
            )

            # Inicializar draft parcial en Firestore
            initial_modules = outline.get("modules", [])
            draft_ref.set({
                "courseTitle": request.courseTitle,
                "level": request.level,
                "durationWeeks": request.durationWeeks,
                "description": request.description,
                "modules": initial_modules,
                "createdBy": uid,
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow(),
                "status": "generating",
            })

            # Emitir outline inicial
            yield f"event: outline\ndata: {json.dumps({'outline': outline})}\n\n"

            expanded_modules = []
            for idx, module in enumerate(outline.get("modules", [])):
                expanded_module = await expand_module(
                    request.courseTitle,
                    request.level,
                    request.durationWeeks,
                    request.description,
                    module,
                )
                expanded_modules.append(expanded_module)

                # Actualizar parcialmente en Firestore
                partial_modules = expanded_modules + outline.get("modules", [])[len(expanded_modules):]
                draft_ref.update({
                    "modules": partial_modules,
                    "updatedAt": datetime.utcnow(),
                })

                # Emitir módulo completado
                yield f"event: module\ndata: {json.dumps({'module': expanded_module, 'index': idx})}\n\n"

            # 3. Construir draft final
            draft_data = {
                "id": draft_id,
                "courseTitle": request.courseTitle,
                "level": request.level,
                "durationWeeks": request.durationWeeks,
                "description": request.description,
                "modules": expanded_modules,
                "createdBy": uid,
                "status": "draft",
                "createdAt": datetime.utcnow().isoformat(),
                "updatedAt": datetime.utcnow().isoformat(),
            }

            draft_ref.update({
                "modules": expanded_modules,
                "updatedAt": datetime.utcnow(),
                "status": "draft",
            })

            yield f"event: done\ndata: {json.dumps({'draftId': draft_id, 'draft': draft_data})}\n\n"
        except Exception as e:
            error_payload = {"error": str(e)}
            # No se actualiza el status para preservar parcial
            yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Nuevo: endpoint para consultar progreso (polling)
@router.get("/drafts/{draft_id}/progress")
async def draft_progress(
    draft_id: str = Path(...),
    auth_data: dict = Depends(get_current_user),
):
    draft_ref = db.collection("drafts").document(draft_id)
    doc = draft_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Draft no encontrado")
    data = doc.to_dict()
    data["id"] = draft_id
    return {"draft": data}


# Actualización de draft parcial
@router.patch("/drafts/{draft_id}")
async def update_draft(
    draft_id: str = Path(...),
    update: CourseDraftUpdateRequest = Depends(),
    auth_data: dict = Depends(get_current_user),
):
    uid = auth_data["uid"]
    draft_ref = db.collection("drafts").document(draft_id)
    doc = draft_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Draft no encontrado")
    data = doc.to_dict()
    if data.get("createdBy") != uid:
        raise HTTPException(status_code=403, detail="No tienes permiso sobre este draft")
    if data.get("status") != "draft":
        raise HTTPException(status_code=400, detail="Solo se pueden editar drafts no publicados")

    updates: dict[str, Any] = {}
    if update.courseTitle is not None:
        updates["courseTitle"] = update.courseTitle
    if update.level is not None:
        updates["level"] = update.level
    if update.durationWeeks is not None:
        updates["durationWeeks"] = update.durationWeeks
    if update.description is not None:
        updates["description"] = update.description
    if update.modules is not None:
        updates["modules"] = [m.dict() for m in update.modules]

    if not updates:
        raise HTTPException(status_code=400, detail="Nada que actualizar")

    updates["updatedAt"] = datetime.utcnow()
    draft_ref.update(updates)
    updated = draft_ref.get().to_dict()
    updated["id"] = draft_id
    return {"draft": updated}


@router.post("/publish-draft/{draft_id}")
async def publish_draft(
    draft_id: str = Path(...),
    body: PublishDraftRequest = Depends(),
    auth_data: dict = Depends(get_current_user),
):
    uid = auth_data["uid"]
    draft_ref = db.collection("drafts").document(draft_id)
    draft_doc = draft_ref.get()
    if not draft_doc.exists:
        raise HTTPException(status_code=404, detail="Draft no encontrado")
    draft = draft_doc.to_dict()
    if draft.get("createdBy") != uid:
        raise HTTPException(status_code=403, detail="No tienes permiso sobre este draft")
    if draft.get("status") != "draft":
        raise HTTPException(status_code=400, detail="Este draft ya fue publicado")

    course_id = str(uuid.uuid4())
    course_ref = db.collection("courses").document(course_id)
    course_ref.set({
        "courseTitle": draft.get("courseTitle"),
        "level": draft.get("level"),
        "durationWeeks": draft.get("durationWeeks"),
        "description": draft.get("description"),
        "author": auth_data.get("name", "") or "",
        "rating": 0.0,
        "reviewCount": 0,
        "enrolledCount": 0,
        "thumbnail": body.thumbnail or "",
        "createdBy": uid,
        "createdAt": datetime.utcnow(),
    })

    modules = draft.get("modules", [])
    for module in modules:
        module_id = str(module.get("moduleNumber", uuid.uuid4()))
        module_ref = course_ref.collection("modules").document(module_id)
        module_ref.set({
            "moduleNumber": module.get("moduleNumber"),
            "moduleTitle": module.get("moduleTitle"),
            "weeks": module.get("weeks", []),
        })

        for topic in module.get("topics", []):
            raw_topic_title = topic.get("topicTitle", "")
            topic_id = slugify(raw_topic_title)
            topic_ref = module_ref.collection("topics").document(topic_id)
            topic_ref.set({
                "topicTitle": raw_topic_title,
            })

            for lesson in topic.get("lessons", []):
                raw_lesson_title = lesson.get("lessonTitle", "")
                lesson_id = slugify(raw_lesson_title)
                lesson_ref = topic_ref.collection("lessons").document(lesson_id)
                lesson_ref.set({
                    "lessonTitle": raw_lesson_title,
                    "theory": lesson.get("theory"),
                    "tests": lesson.get("tests", []),
                })

    draft_ref.update({
        "status": "published",
        "publishedAt": datetime.utcnow(),
        "courseId": course_id,
    })

    created_course_doc = course_ref.get()
    course_data = created_course_doc.to_dict()
    course_data["id"] = course_id
    return {"course": course_data}
