"""
AI agent for the director's Telegram queries.

Uses OpenRouter (OpenAI-compatible API) with tool_use to answer
natural-language questions about project status in Russian.

Adding write tools in the future:
  register a new entry in TOOL_REGISTRY with schema + async handler.
  The agent loop picks it up automatically.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Tuple

from openai import AsyncOpenAI

from app.notifications.telegram import send_telegram
from bitrix.client import BitrixClient
from bitrix import project_analytics as analytics
from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Ты ассистент директора строительной компании.
Отвечай ТОЛЬКО на русском языке.
Используй Telegram Markdown — **жирный** для ключевых чисел и названий,
— для пунктов, эмодзи в меру.

Твоя задача — предоставлять точную информацию о строительных проектах:
прогресс, сроки, бюджет план/факт, отклонения.

Правила:
1. Если проект не назван явно — сначала вызови list_projects и предложи
   пользователю выбрать из списка.
2. Если проект упомянут нечётко — подбери наиболее похожее название из списка.
3. Если ничего не найдено — ответь:
   «Не могу найти проект. Вот доступные: <список>. Уточните название.»
4. При показе бюджетов всегда указывай три категории:
   Материалы / ФОТ (зарплата) / Техника — план и факт.
5. Если факт > план — выдели это явно как отклонение.
6. Для неизвестных запросов подскажи примеры:
   «Прогресс по объекту X», «Бюджет этапа Y», «Что начнётся на этой неделе».
7. Числа форматируй: 105 000 ₽ (пробел как разделитель тысяч).
8. Даты в формате ДД.ММ.ГГГГ.
"""

# ---------------------------------------------------------------------------
# Tool registry: name → (json_schema, async handler)
# ---------------------------------------------------------------------------

ToolHandler = Callable[..., Coroutine[Any, Any, Any]]
ToolEntry = Tuple[Dict[str, Any], ToolHandler]

# Populated at module load; add new tools here to extend the agent.
TOOL_REGISTRY: Dict[str, ToolEntry] = {}


def _register(schema: Dict[str, Any]) -> Callable[[ToolHandler], ToolHandler]:
    def decorator(fn: ToolHandler) -> ToolHandler:
        TOOL_REGISTRY[schema["function"]["name"]] = (schema, fn)
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Tool definitions + handlers
# ---------------------------------------------------------------------------

@_register({
    "type": "function",
    "function": {
        "name": "list_projects",
        "description": "Вернуть список всех активных строительных проектов с их ID и названиями.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
})
async def _tool_list_projects(**_: Any) -> Any:
    async with BitrixClient() as client:
        return await analytics.list_projects(client)


@_register({
    "type": "function",
    "function": {
        "name": "get_schedule_analysis",
        "description": (
            "Анализ выполнения задач по расписанию: что просрочено, что выполнено, "
            "что в работе, что не начато. Включает бюджет факт по задачам."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "ID проекта (из list_projects)",
                },
            },
            "required": ["project_id"],
        },
    },
})
async def _tool_get_schedule_analysis(project_id: int, **_: Any) -> Any:
    async with BitrixClient() as client:
        return await analytics.get_schedule_analysis(client, project_id)


@_register({
    "type": "function",
    "function": {
        "name": "get_budget_overview",
        "description": (
            "Бюджет по этапам: план vs факт с разбивкой по категориям "
            "(Материалы, ФОТ, Техника). Показывает отклонения."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "ID проекта (из list_projects)",
                },
            },
            "required": ["project_id"],
        },
    },
})
async def _tool_get_budget_overview(project_id: int, **_: Any) -> Any:
    async with BitrixClient() as client:
        return await analytics.get_budget_overview(client, project_id)


@_register({
    "type": "function",
    "function": {
        "name": "get_resource_costs",
        "description": (
            "Детальные затраты по ресурсам: материалы, трудозатраты, техника — "
            "каждая строка с планом и фактом. Можно фильтровать по этапу и задаче."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "ID проекта",
                },
                "etap": {
                    "type": "string",
                    "description": "Название этапа для фильтрации (необязательно)",
                },
                "zadacha": {
                    "type": "string",
                    "description": "Название задачи для фильтрации (необязательно)",
                },
            },
            "required": ["project_id"],
        },
    },
})
async def _tool_get_resource_costs(project_id: int, etap: str | None = None, zadacha: str | None = None, **_: Any) -> Any:
    async with BitrixClient() as client:
        return await analytics.get_resource_costs(client, project_id, etap=etap, zadacha=zadacha)


@_register({
    "type": "function",
    "function": {
        "name": "get_upcoming_tasks",
        "description": "Задачи, которые начинаются или должны завершиться в ближайшие N дней.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "ID проекта",
                },
                "days": {
                    "type": "integer",
                    "description": "Окно в днях (по умолчанию 7)",
                    "default": 7,
                },
            },
            "required": ["project_id"],
        },
    },
})
async def _tool_get_upcoming_tasks(project_id: int, days: int = 7, **_: Any) -> Any:
    async with BitrixClient() as client:
        return await analytics.get_upcoming_tasks(client, project_id, days=days)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

_MAX_TOOL_ROUNDS = 6


async def handle_director_query(chat_id: int, text: str) -> None:
    """
    Entry point: receive a free-text message from the director,
    run the tool-use loop, send the final response to Telegram.
    """
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

        # Fallback if we exhausted rounds without a final answer
        await send_telegram(
            "Не удалось получить ответ — слишком много шагов. Попробуйте уточнить вопрос.",
            chat_id=str(chat_id),
        )

    except Exception as exc:
        logger.exception(f"Director agent error for chat {chat_id}: {exc}")
        await send_telegram(
            "Произошла ошибка при обработке запроса. Попробуйте позже.",
            chat_id=str(chat_id),
        )


async def _dispatch(name: str, arguments_json: str) -> Any:
    """Call the registered tool handler by name."""
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return {"error": f"Неизвестный инструмент: {name}"}
    _, handler = entry
    try:
        kwargs = json.loads(arguments_json) if arguments_json else {}
        return await handler(**kwargs)
    except Exception as exc:
        logger.exception(f"Tool '{name}' raised: {exc}")
        return {"error": str(exc)}
