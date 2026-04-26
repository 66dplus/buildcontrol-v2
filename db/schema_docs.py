"""
Schema documentation embedded in the Telegram director agent's system prompt.

Describes every table and its ambiguous columns so the LLM can generate
correct SQL without needing to guess column semantics.
"""

SCHEMA_DOCS = """
=== ТАБЛИЦЫ БАЗЫ ДАННЫХ ===

projects(id, name, is_archived)
  id   — числовой ID проекта (Bitrix workgroup), используется как FK везде
  name — название, например «ЖК Питер», «Объект ул. Ленина»

tasks(project_id, phase, task_name,
      date_start_plan, date_end_plan, date_start_actual, date_end_actual,
      budget_plan, budget_actual, completion_pct, stage_name,
      bitrix_task_id, bitrix_element_id)
  phase          — название этапа с числовым префиксом («1. Подготовительные работы», «2. Земляные работы», «3. Фундамент» и т.д.)
                   При поиске используй py_lower(phase) LIKE '%фундамент%' (без номера, substring match)
  task_name      — название задачи
  completion_pct — % выполнения (0–100), заполняется прорабом
  budget_actual  — фактические затраты в ₽ (каскад: сумма из materials + labor + equipment)
  date_*_plan    — плановые даты в формате YYYY-MM-DD (ISO 8601, совместимо с date('now'))
  date_*_actual  — фактические даты (NULL если не начато / не завершено)
  stage_name     — текущая стадия Kanban («Новая», «В работе», «Завершена» и т.д.)

materials(project_id, phase, task_name, material_name, unit,
          price_plan, qty_plan, cost_plan,
          price_actual, qty_bought, qty_consumed, qty_stock, cost_actual)
  unit          — единица измерения (л, м³, шт, кг, м² и т.д.)
  qty_bought    — КУПЛЕНО всего (поступило на склад с момента начала проекта)
  qty_consumed  — ИЗРАСХОДОВАНО на объекте (ушло в дело, заполняет прораб)
  qty_stock     — ОСТАТОК на складе = qty_bought − qty_consumed
  cost_plan     = qty_plan × price_plan
  cost_actual   = qty_consumed × price_actual  (стоимость израсходованного)
  price_actual  — средневзвешенная цена покупки (обновляется при каждой закупке)

  ВАЖНО: qty_bought ≠ qty_consumed. «Что куплено» → qty_bought.
         «Что использовано / потрачено» → qty_consumed. «На складе» → qty_stock.
  ВАЖНО: Каждый материал хранится ОТДЕЛЬНО для каждой задачи (phase, task_name).
         Для получения итогов по проекту — используй SUM() GROUP BY material_name, unit.

labor(project_id, phase, task_name, specialty, rate,
      hours_plan, payroll_plan, hours_actual, payroll_actual)
  specialty      — специальность (Машинист, Разнорабочий, Монтажник и т.д.)
  rate           — ставка ₽/час
  hours_actual   — фактически отработанные часы
  payroll_actual = hours_actual × rate

equipment_items(project_id, phase, task_name, equipment_name,
                price_per_hour, hours_plan, total_plan,
                hours_actual, total_actual)
  equipment_name — название техники (Экскаватор, Самосвал и т.д.)
  price_per_hour — аренда ₽/час
  total_actual   = hours_actual × price_per_hour

budget_phases(project_id, phase_name,
              materials_plan, labor_plan, equipment_plan, total_plan,
              materials_actual, labor_actual, equipment_actual, total_actual)
  Агрегат по этапу — обновляется каскадом после каждого отчёта прораба.
  Для быстрого обзора бюджета лучше использовать эту таблицу, а не суммировать materials/labor/equipment вручную.

  ВАЖНО: total_plan и total_actual могут быть 0 (NULL-эквивалент), даже если компоненты заполнены.
  ВСЕГДА считай их через COALESCE:
      plan_total  = COALESCE(NULLIF(total_plan,0),   materials_plan+labor_plan+equipment_plan)
      fact_total  = COALESCE(NULLIF(total_actual,0), materials_actual+labor_actual+equipment_actual)
  Если оба равны 0 — этап действительно без плана/факта. Не пиши «0 ₽ из 0 ₽» — пропусти этап
  или сгруппируй с пометкой «без затрат».

purchase_requests(id, project_id, status, items_json, buyer_comment,
                  created_at, resolved_at, actor, approver_comment,
                  tg_message_id, tg_chat_id)
  status     — «pending» (ожидает) | «approved» (одобрено) | «rejected» (отклонено)
  items_json — JSON-массив позиций: [{material_name, unit, qty, price, price_plan}, ...]
  actor      — кто принял решение (имя согласующего)

=== ВАЖНЫЕ ПРАВИЛА ДЛЯ SQL ===

1. КИРИЛЛИЦА LIKE — Встроенный LOWER() в SQLite НЕ работает для кириллицы.
   Используй функцию py_lower() — она корректно переводит русский текст в нижний регистр.
   НЕПРАВИЛЬНО: WHERE material_name LIKE '%топливо%'
   НЕПРАВИЛЬНО: WHERE py_lower(material_name) LIKE '%топливо%'
   ПРАВИЛЬНО:   WHERE py_lower(material_name) LIKE '%топливо%'
   Применяй py_lower() ко всем столбцам с русским текстом при поиске по ключевым словам.

2. ДАТЫ — хранятся в формате YYYY-MM-DD. Сравнение с date('now') работает корректно.
   WHERE date_end_plan < date('now')  ← правильно
   WHERE date_start_plan BETWEEN date('now') AND date('now', '+30 days')  ← правильно

3. ПОИСК ПРОЕКТА — всегда использй py_lower(p.name) LIKE '%ключевое_слово%'.

=== ТИПИЧНЫЕ ЗАПРОСЫ ===

-- Что куплено по проекту (qty_bought = купленное, а не остаток):
SELECT m.material_name, m.unit, m.qty_bought, m.qty_consumed, m.qty_stock, m.cost_actual
FROM materials m
JOIN projects p ON p.id = m.project_id
WHERE py_lower(p.name) LIKE '%питер%';

-- Остатки конкретного материала (используй LOWER для кириллицы!):
SELECT material_name, unit, qty_stock
FROM materials
WHERE project_id = (SELECT id FROM projects WHERE LOWER(name) LIKE '%питер%' LIMIT 1)
  AND LOWER(material_name) LIKE '%топливо%';

-- Использование бюджета по этапам (используй COALESCE — total_plan/total_actual могут быть 0):
SELECT bp.phase_name,
       COALESCE(NULLIF(bp.total_plan,0),
                bp.materials_plan + bp.labor_plan + bp.equipment_plan)   AS plan_total,
       COALESCE(NULLIF(bp.total_actual,0),
                bp.materials_actual + bp.labor_actual + bp.equipment_actual) AS fact_total
FROM budget_phases bp
JOIN projects p ON p.id = bp.project_id
WHERE py_lower(p.name) LIKE '%питер%'
ORDER BY bp.phase_name;

-- Итоговый бюджет проекта (сумма по всем этапам):
SELECT SUM(COALESCE(NULLIF(bp.total_plan,0),
                    bp.materials_plan + bp.labor_plan + bp.equipment_plan))   AS plan_total,
       SUM(COALESCE(NULLIF(bp.total_actual,0),
                    bp.materials_actual + bp.labor_actual + bp.equipment_actual)) AS fact_total
FROM budget_phases bp
JOIN projects p ON p.id = bp.project_id
WHERE py_lower(p.name) LIKE '%питер%';

-- Просроченные задачи:
SELECT t.phase, t.task_name, t.date_end_plan, t.completion_pct
FROM tasks t
JOIN projects p ON p.id = t.project_id
WHERE py_lower(p.name) LIKE '%питер%'
  AND t.date_end_plan < date('now')
  AND t.completion_pct < 100;

-- Задачи на ближайшие 30 дней:
SELECT t.phase, t.task_name, t.date_start_plan, t.date_end_plan, t.completion_pct
FROM tasks t
JOIN projects p ON p.id = t.project_id
WHERE py_lower(p.name) LIKE '%питер%'
  AND (t.date_start_plan BETWEEN date('now') AND date('now', '+30 days')
    OR t.date_end_plan BETWEEN date('now') AND date('now', '+30 days'));

-- Ожидающие заявки на закупку:
SELECT pr.id, p.name AS project, pr.created_at, pr.items_json
FROM purchase_requests pr
JOIN projects p ON p.id = pr.project_id
WHERE pr.status = 'pending';
"""
