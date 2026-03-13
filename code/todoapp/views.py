import json
import os
from functools import wraps
from typing import Any
from urllib import error, request as urllib_request

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import ToDo


def _json_body(request) -> dict[str, Any]:
    content_type = (request.content_type or "").split(";", 1)[0].strip().lower()
    if content_type == "multipart/form-data":
        return {}
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _get_param(request, data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
        if key in request.POST and request.POST.get(key) not in (None, ""):
            return request.POST.get(key)
    return default


def _parse_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    value_str = str(value).strip().lower()
    if value_str in {"1", "true", "yes", "on"}:
        return True
    if value_str in {"0", "false", "no", "off"}:
        return False
    return default


def _ollama_settings() -> tuple[str, str, float]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://gcb-ai-model:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "gemma3:1b")
    timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
    return base_url, model, timeout


def _generate_with_ollama(prompt: str, model: str | None = None) -> tuple[str | None, int, int, str | None]:
    base_url, default_model, timeout = _ollama_settings()
    payload = {
        "model": model or default_model,
        "prompt": prompt,
        "stream": False,
    }

    req = urllib_request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return None, 0, 0, f"Ollama returned HTTP {exc.code}: {detail}"
    except error.URLError as exc:
        return None, 0, 0, f"Unable to reach Ollama: {exc.reason}"

    try:
        response_data = json.loads(raw_body)
    except json.JSONDecodeError:
        return None, 0, 0, "Ollama returned invalid JSON"

    content = response_data.get("response")
    if not isinstance(content, str):
        return None, 0, 0, "Ollama response did not include generated content"

    prompt_tokens = response_data.get("prompt_eval_count")
    if not isinstance(prompt_tokens, int):
        prompt_tokens = 0

    generated_tokens = response_data.get("eval_count")
    if not isinstance(generated_tokens, int):
        generated_tokens = 0

    return content, prompt_tokens, generated_tokens, None


def require_login(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"ok": False, "error": "authentication required"}, status=401)
        return view_func(request, *args, **kwargs)

    return wrapper


@csrf_exempt
def login_view(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    data = _json_body(request)
    username = _get_param(request, data, "username", "Username")
    password = _get_param(request, data, "password", "Password")
    print(f"Login attempt: username={username}, password={password}")

    if not username or not password:
        return JsonResponse({"ok": False, "error": "username and password required"}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"ok": False, "error": "invalid credentials"}, status=401)

    login(request, user)
    return JsonResponse({"ok": True, "user": {"id": user.id, "username": user.username}})


@csrf_exempt
def logout_view(request):
    if request.method not in {"POST", "GET"}:
        return JsonResponse({"ok": False, "error": "POST or GET required"}, status=405)

    logout(request)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_login
def create_todo(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    data = _json_body(request)
    title = _get_param(request, data, "title", "Title")
    text = _get_param(request, data, "text", "Text", default="")
    upload = request.FILES.get("file") or request.FILES.get("File")

    if not title:
        return JsonResponse({"ok": False, "error": "title required"}, status=400)

    todo = ToDo.objects.create(user=request.user, title=title, text=text, file=upload)

    return JsonResponse(
        {
            "ok": True,
            "todo": {
                "id": todo.id,
                "title": todo.title,
                "text": todo.text,
                "done": todo.done,
                "file": request.build_absolute_uri(todo.file.url) if todo.file else None,
            },
        }
    )


@csrf_exempt
@require_login
def mark_done(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    data = _json_body(request)
    todo_id = _get_param(request, data, "id", "todo_id", "ToDoId")
    done_value = _get_param(request, data, "done", "Done")

    if not todo_id:
        return JsonResponse({"ok": False, "error": "todo id required"}, status=400)

    try:
        todo = ToDo.objects.get(id=todo_id, user=request.user)
    except ToDo.DoesNotExist:
        return JsonResponse({"ok": False, "error": "todo not found"}, status=404)

    todo.done = _parse_bool(done_value, default=True)
    todo.save(update_fields=["done"])

    return JsonResponse({"ok": True, "todo": {"id": todo.id, "done": todo.done}})


@csrf_exempt
@require_login
def get_todos(request):
    if request.method != "GET":
        return JsonResponse({"ok": False, "error": "GET required"}, status=405)

    todos = (
        ToDo.objects.filter(user=request.user)
        .order_by("-created_at")
        .all()
    )

    items = []
    for todo in todos:
        items.append(
            {
                "id": todo.id,
                "title": todo.title,
                "text": todo.text,
                "done": todo.done,
                "file": request.build_absolute_uri(todo.file.url) if todo.file else None,
                "created_at": todo.created_at.isoformat(),
            }
        )

    return JsonResponse({"ok": True, "todos": items})


@csrf_exempt
def ai_autocomplete(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    data = _json_body(request)
    prompt = _get_param(request, data, "prompt", "Prompt")
    model = _get_param(request, data, "model", "Model")

    if not prompt:
        return JsonResponse({"ok": False, "error": "prompt required"}, status=400)

    content, prompt_tokens, generated_tokens, error_message = _generate_with_ollama(prompt, model=model)
    if error_message:
        return JsonResponse({"ok": False, "error": error_message}, status=502)

    response = JsonResponse(
        {
            "ok": True,
            "content": content,
            "prompt_tokens": prompt_tokens,
            "generated_tokens": generated_tokens,
        }
    )
    response["X-Prompt-Tokens"] = str(prompt_tokens)
    response["X-Generated-Tokens"] = str(generated_tokens)
    return response

@csrf_exempt
@require_login
def delete_all_todos(request):
    if request.method not in {"POST", "DELETE"}:
        return JsonResponse({"ok": False, "error": "POST or DELETE required"}, status=405)

    deleted_count, _ = ToDo.objects.filter(user=request.user).delete()
    return JsonResponse({"ok": True, "deleted": deleted_count})
