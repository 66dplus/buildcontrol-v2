"""
AI director agent for BuildControl Telegram bot.

Architecture: 2 tools only.
  1. list_projects()      — fuzzy project-name resolution
  2. query_database(sql)  — arbitrary SELECT against the local SQLite DB

The agent's system prompt embeds the full schema knowledge base (db/schema_docs.py)
so the LLM generates correct SQL and understands field semantics (e.g. qty_bought
vs qty_consumed vs qty_stock) without any hardcoded field logic here.

Adding new analytical capabilities = update SCHEMA_DOCS, not Python code.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Tuple

import aiosqlite
from openai import AsyncOpenAI

from app.notifications.telegram import send_telegram
from bitrix.client import BitrixClient
from bitrix.methods import workgroups
from config import settings
from db.database import get_db
from db.schema_docs import SCHEMA_DOCS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""Ты ассистент директора строительной компании.
Отвечай ТОЛЬКО на русском языке.
Используй HTML-теги Telegram: <b>жирный</b> для ключевых чисел, эмодзи в меру.

{SCHEMA_DOCS}

== ПРАВИЛА РАБОТЫ ==
1. Для ответа на вопрос:
   а) Вызови list_projects() чтобы найти project_id по частичному совпадению имени.
   б) Составь минимальный SQL-запрос, отвечающий именно на заданный вопрос.
   в) Если результат выглядит неполным или пустым — уточни запрос и повтори (max 2 попытки).
2. Отвечай ТОЛЬКО на то, о чём спросили. Не выдавай полный отчёт на каждый вопрос.
   — Вопрос о закупках → только закупки.
   — Вопрос о бюджете → только бюджет.
   — Вопрос о задачах → только задачи и сроки.
3. Закупки — строго различай:
   qty_bought = куплено (поступило на склад), qty_consumed = израсходовано на объекте,
   qty_stock = остаток на складе. В ответе указывай реальные единицы (л, м³, шт и т.д.).
4. Бюджет: показывай использование, а не отклонение.
   Формат: "<b>30 000 ₽</b> из 600 000 ₽ (5%)".
   Жирный и предупреждение ⚠️ только если факт > план (перерасход).
   ВАЖНО: для total_plan/total_actual всегда используй COALESCE через компоненты
   (materials_plan + labor_plan + equipment_plan). Если итоговый план = 0 — НЕ пиши
   "0 ₽ из 0 ₽": либо пропусти этап, либо сгруппируй как «без плана».
5. Числа: 105 000 ₽. Даты: ДД.ММ.ГГГГ.
6. Завершай каждый ответ 1–2 краткими предложениями с предложением уточнить:
   "Хотите узнать [X]? Или показать [Y]?"
7. Если данных нет — скажи прямо, не выдумывай. Если проект не найден через list_projects —
   так и скажи, не сочиняй.
"""

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

ToolHandler = Callable[..., Coroutine[Any, Any, Any]]
ToolEntry = Tuple[Dict[str, Any], ToolHandler]

TOOL_REGISTRY: Dict[str, ToolEntry] = {}


def _register(schema: Dict[str, Any]) -> Callable[[ToolHandler], ToolHandler]:
    def decorator(fn: ToolHandler) -> ToolHandler:
        TOOL_REGISTRY[schema["function"]["name"]] = (schema, fn)
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@_register({
    "type": "function",
    "function": {
        "name": "list_projects",
        "description": "Вернуть список всех активных строительных проектов с их ID и названиями. Вызывай первым для определения project_id.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
})
async def _tool_list_projects(**_: Any) -> Any:
    async with get_db() as conn:
        async with conn.execute(
            "SELECT id, name FROM projects WHERE is_archived=0 ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
            return [{"id": r[0], "name": r[1]} for r in rows]


@_register({
    "type": "function",
    "function": {
        "name": "query_database",
        "description": (
            "Выполнить SELECT-запрос к локальной базе данных проекта. "
            "Возвращает список строк в виде объектов. "
            "Используй схему из системного промпта для составления правильных запросов."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Корректный SQL SELECT-запрос к SQLite",
                }
            },
            "required": ["sql"],
        },
    },
})
async def _tool_query_database(sql: str, **_: Any) -> Any:
    sql_clean = sql.strip().rstrip(";")
    if not sql_clean.upper().lstrip().startswith("SELECT"):
        return {"error": "Только SELECT-запросы разрешены"}
    if "LIMIT" not in sql_clean.upper():
        sql_clean += " LIMIT 200"
    try:
        async with get_db() as conn:
            async with conn.execute(sql_clean) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("query_database failed for sql=%r: %s", sql_clean, exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

_MAX_TOOL_ROUNDS = 8


async def handle_director_query(chat_id: int, text: str) -> None:
    """Entry point: run the tool-use loop, send final reply to Telegram."""
    if not settings.openrouter_api_key:
        logger.error("OPENROUTER_API_KEY not set — director agent disabled")
        await send_telegram(
            "⚙️ Агент не настроен. Обратитесь к администратору.",
            chat_id=str(chat_id),
        )
        return

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    tools: List[Dict[str, Any]] = [schema for schema, _ in TOOL_REGISTRY.values()]
    messages: List[Dict[str, Any]] = [{"role": "user", "content": text}]

    try:
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(
                model=settings.openrouter_model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                tools=tools,
                tool_choice="auto",
            )

            choice = response.choices[0]
            msg = choice.message

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                messages.append(msg.model_dump(exclude_unset=True))
                for call in msg.tool_calls:
                    result = await _dispatch(call.function.name, call.function.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
            else:
                reply = (msg.content or "").strip()
                await send_telegram(reply or "Нет данных.", chat_id=str(chat_id))
                return

        await send_telegram(
            "Не удалось получить ответ — слишком много шагов. Попробуйте уточнить вопрос.",
            chat_id=str(chat_id),
        )

    except Exception as exc:
        logger.exception("Director agent error for chat %s: %s", chat_id, exc)
        await send_telegram(
            "Произошла ошибка при обработке запроса. Попробуйте позже.",
            chat_id=str(chat_id),
        )


async def _dispatch(name: str, arguments_json: str) -> Any:
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return {"error": f"Неизвестный инструмент: {name}"}
    _, handler = entry
    try:
        kwargs = json.loads(arguments_json) if arguments_json else {}
        return await handler(**kwargs)
    except Exception as exc:
        logger.exception("Tool '%s' raised: %s", name, exc)
        return {"error": str(exc)}
