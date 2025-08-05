import os
import json
import math
from dotenv import load_dotenv
import anyio
from openai import OpenAI

load_dotenv()

def get_openrouter_client() -> OpenAI:
    base_url = "https://openrouter.ai/api/v1"
    api_key = os.getenv("OPENROUTER_API_KEY")
    return OpenAI(base_url=base_url, api_key=api_key)

def clean_code_fences(text: str) -> str:
    return text.replace("```json", "").replace("```", "").strip()

def try_repair_json(raw: str) -> dict | None:
    cleaned = clean_code_fences(raw)
    start = cleaned.find("{")
    if start == -1:
        return None

    stack = []
    for i in range(start, len(cleaned)):
        char = cleaned[i]
        if char == "{":
            stack.append("{")
        elif char == "}":
            if stack:
                stack.pop()
                if not stack:
                    candidate = cleaned[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    # Si quedó abierto, reequilibrar agregando '}' faltantes
    balance = 0
    for c in cleaned[start:]:
        if c == "{":
            balance += 1
        elif c == "}":
            balance -= 1
    candidate = cleaned[start:]
    if balance > 0:
        candidate += "}" * balance
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None

async def call_model_single(prompt: str, max_tokens: int = 1200) -> str:
    client = get_openrouter_client()

    def call():
        extra_headers = {}
        site_url = os.getenv("OPENROUTER_SITE_URL")
        site_name = os.getenv("OPENROUTER_SITE_NAME")
        if site_url:
            extra_headers["HTTP-Referer"] = site_url
        if site_name:
            extra_headers["X-Title"] = site_name

        return client.chat.completions.create(
            model="google/gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.65,
            max_tokens=max_tokens,
            extra_headers=extra_headers,
        )

    completion = await anyio.to_thread.run_sync(call)
    try:
        return completion.choices[0].message.content
    except Exception:
        return ""

async def generate_outline_attempt(prompt: str, max_tokens: int = 1200) -> str:
    try:
        return await call_model_single(prompt, max_tokens=max_tokens)
    except Exception as e:
        print(f"[ai_generator] error en outline attempt: {e}")
        return ""

def build_fallback_outline(duration_weeks: int) -> dict:
    num_modules = max(1, math.ceil(duration_weeks / 2))
    weeks_ranges = []
    week = 1
    for i in range(num_modules):
        if week + 1 <= duration_weeks:
            weeks_ranges.append([week, week + 1])
            week += 2
        else:
            weeks_ranges.append(list(range(week, duration_weeks + 1)))
            week = duration_weeks + 1

    modules = []
    for idx, wr in enumerate(weeks_ranges, start=1):
        modules.append({
            "moduleNumber": idx,
            "moduleTitle": f"Módulo {idx}",
            "weeks": wr,
            "topics": [
                {
                    "topicTitle": f"Tópico {idx}-1",
                    "lessons": [
                        {"lessonTitle": f"Lección {idx}-1"}
                    ],
                }
            ],
        })
    return {"modules": modules}

async def generate_outline(
    course_title: str,
    level: str,
    duration_weeks: int,
    description: str,
) -> dict:
    """
    Fase 1: genera outline adaptado a duration_weeks (un módulo cada ~2 semanas).
    """
    num_modules = max(1, math.ceil(duration_weeks / 2))
    # Calcular rangos de semanas consecutivas
    weeks_ranges = []
    week = 1
    for _ in range(num_modules):
        if week + 1 <= duration_weeks:
            weeks_ranges.append([week, week + 1])
            week += 2
        else:
            weeks_ranges.append(list(range(week, duration_weeks + 1)))
            week = duration_weeks + 1

    # Ejemplo para el prompt
    example_modules = []
    for idx, wr in enumerate(weeks_ranges, start=1):
        example_modules.append({
            "moduleNumber": idx,
            "moduleTitle": f"Título del módulo {idx}",
            "weeks": wr,
            "topics": [
                {
                    "topicTitle": f"Título del tópico {idx}-1",
                    "lessons": [
                        {"lessonTitle": f"Título de la lección {idx}-1"}
                    ],
                }
            ],
        })
    example_json = {"modules": example_modules}

    prompt = f"""
Genera la estructura de un curso titulado "{course_title}".
Nivel: {level}
Duración: {duration_weeks} semanas
Descripción: {description}

Quiero {num_modules} módulos. Cada módulo debe cubrir un bloque de semanas consecutivas según la duración: {weeks_ranges}.
Cada módulo debe tener:
- moduleNumber (del 1 al {num_modules})
- moduleTitle descriptivo
- weeks acorde al bloque
- 1 o 2 topics por módulo, cada uno con topicTitle
- Cada topic debe tener exactamente una lección con lessonTitle

Devuélveme únicamente un JSON válido similar a este ejemplo (sin texto explicativo adicional):
{json.dumps(example_json, indent=2)}
"""

    outline = None
    raw = ""
    for attempt in range(3):
        raw = await generate_outline_attempt(prompt)
        parsed = try_repair_json(raw)
        if parsed and isinstance(parsed.get("modules"), list) and len(parsed["modules"]) >= 1:
            outline = parsed
            break
        await anyio.sleep(0.5 * (attempt + 1))
    if not outline:
        outline = build_fallback_outline(duration_weeks)
        print(f"[ai_generator] fallback outline usado, raw último: {raw[:800]}")
    return outline

# Nueva función para generar outline temporal (sin persistir)
async def generate_outline_temporary(
    course_title: str,
    level: str,
    duration_weeks: int,
    description: str,
) -> dict:
    """
    Genera outline temporal sin persistir en base de datos
    """
    return await generate_outline(course_title, level, duration_weeks, description)

async def expand_lesson(
    course_title: str,
    level: str,
    duration_weeks: int,
    description: str,
    module_title: str,
    topic_title: str,
    lesson_title: str,
) -> dict:
    """
    Fase 2: para una lección concreta genera theory >=150 palabras y un test.
    """
    prompt = f"""
Tienes esta lección:
{{
  "lessonTitle": "{lesson_title}",
  "moduleTitle": "{module_title}",
  "topicTitle": "{topic_title}",
  "courseTitle": "{course_title}",
  "level": "{level}",
  "durationWeeks": {duration_weeks},
  "description": "{description}"
}}

Genera un objeto JSON con:
- theory: una explicación teórica clara y bien estructurada de al menos 150 palabras (como una clase).
- tests: una lista con un test que incluya question, options (mínimo 3), answer y solution.

Respuesta en solo JSON con este formato:
{{
  "lessonTitle": "{lesson_title}",
  "theory": "... (>=150 palabras) ...",
  "tests": [
    {{
      "question": "...",
      "options": ["...", "...", "..."],
      "answer": "...",
      "solution": "..."
    }}
  ]
}}
"""
    raw = await call_model_single(prompt, max_tokens=1100)
    parsed = try_repair_json(raw)
    if not parsed:
        raise ValueError(f"Expansion inválida (no JSON) para lección '{lesson_title}': {raw[:400]}")
    theory = parsed.get("theory", "")
    if not theory or len(theory.split()) < 150:
        raise ValueError(f"Expansion inválida (theory corta) para lección '{lesson_title}': words={len(theory.split())}")
    return parsed

async def expand_module(
    course_title: str,
    level: str,
    duration_weeks: int,
    description: str,
    module: dict,
) -> dict:
    """
    Expande un módulo completo (cada lección) añadiendo theory y tests.
    """
    mod_title = module.get("moduleTitle", "")
    for topic in module.get("topics", []):
        top_title = topic.get("topicTitle", "")
        new_lessons = []
        for lesson in topic.get("lessons", []):
            lt = lesson.get("lessonTitle", "")
            try:
                expanded = await expand_lesson(
                    course_title,
                    level,
                    duration_weeks,
                    description,
                    mod_title,
                    top_title,
                    lt,
                )
                new_lessons.append(expanded)
            except Exception as e:
                print(f"[ai_generator] fallback lección '{lt}': {e}")
                new_lessons.append({
                    "lessonTitle": lt,
                    "theory": "Teoría detallada de al menos 150 palabras debería ir aquí.",
                    "tests": [
                        {
                            "question": "Pregunta de ejemplo?",
                            "options": ["A", "B", "C"],
                            "answer": "A",
                            "solution": "Porque A es correcto.",
                        }
                    ],
                })
        topic["lessons"] = new_lessons
    return module

async def generate_course_structure(
    course_title: str,
    level: str,
    duration_weeks: int,
    description: str,
) -> dict:
    """
    Orquesta outline y expansión por módulo completo.
    """
    outline = await generate_outline(course_title, level, duration_weeks, description)

    for module in outline.get("modules", []):
        expanded = await expand_module(
            course_title,
            level,
            duration_weeks,
            description,
            module,
        )
        module.update(expanded)

    return outline