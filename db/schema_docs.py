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
  stage_name     — текущая стадия Kanban. Терминальные значения зафиксированы:
                   «Новая» (первая колонка) и «Завершена» (последняя). Промежуточные
                   стадии — это пользовательские названия из Bitrix («Выполняются»,
                   «В работе», «В процессе», «На проверке» и т.п.) — НЕ хардкодить их.
                   Для «задачи в работе» используй ОТРИЦАНИЕ:
                       stage_name NOT IN ('Новая', 'Завершена') AND stage_name IS NOT NULL
                   ВНИМАНИЕ: для части задач stage_name может быть NULL (нет
                   bitrix_task_id или канбан ещё не двигали). Если stage_name IS NULL,
                   страхуйся мягкими сигналами: «в работе» = completion_pct > 0 AND
                   completion_pct < 100, ИЛИ date_start_actual IS NOT NULL AND
                   date_start_actual <> '' AND (date_end_actual IS NULL OR
                   date_end_actual = '').
                   Не пиши «нет задач в работе» только потому, что stage_name пустой —
                   проверь обе ветки.

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

  ВАЖНО: «перерасход цены» ≠ «статус rejected».
  rejected = согласующий вручную отказал. Это НЕ признак перерасхода цены.
  Перерасход = price > price_plan хотя бы для одной позиции в items_json, НЕЗАВИСИМО от статуса.
  Одобренная заявка может содержать перерасход (директор принял решение осознанно).
  Для вопросов «Есть перерасход по материалам?» проверяй ВСЕ ЧЕТЫРЕ источника:
    а) purchase_requests.items_json — цена позиции закупки vs плановая цена
    б) materials.price_actual vs materials.price_plan — средневзвешенная цена по материалам
    в) materials: qty_consumed/qty_plan >> AVG(task completion_pct) + 15% — мягкий сигнал темпа
    г) budget_phases.materials_actual vs materials_plan — АГРЕГИРОВАННЫЕ материальные затраты
       (используй этот источник ВСЕГДА, особенно если в таблице materials или purchase_requests
        нет записей для проекта — budget_phases всегда содержит итог).

  Алгоритм: проверь sources а–г. Если хоть один показывает перерасход — сообщи о нём.
  Если materials и purchase_requests пусты, но budget_phases показывает materials_actual > materials_plan
  — это НАСТОЯЩИЙ перерасход по материалам. Сообщи директору.

  ВАЖНО: любое превышение price > price_plan / materials_actual > materials_plan считается
  перерасходом — даже 0.1%. НЕ округляй и не сглаживай разницу до нуля,
  не пиши «незначительное отклонение».

  ФОРМАТ ответа при перерасходе (обязателен):
  «По цене есть перерасход: {overspend_rub} ₽.
   В запланированном бюджете стоимость составляет {plan_total} ₽,
   а закупка идёт на {actual_total} ₽ (+{dev_pct}%).»
  Всегда указывай ИТОГОВЫЕ суммы (qty × price), а не цены за единицу.

=== ВАЖНЫЕ ПРАВИЛА ДЛЯ SQL ===

1. КИРИЛЛИЦА LIKE — Встроенный LOWER() в SQLite НЕ работает для кириллицы.
   Используй функцию py_lower() — она корректно переводит русский текст в нижний регистр.
   НЕПРАВИЛЬНО: WHERE material_name LIKE '%топливо%'
   ПРАВИЛЬНО:   WHERE py_lower(material_name) LIKE '%топливо%'
   Применяй py_lower() ко всем столбцам с русским текстом при поиске по ключевым словам.

2. ДАТЫ — хранятся в формате YYYY-MM-DD. Сравнение с date('now') работает корректно.
   WHERE date_end_plan < date('now')  ← правильно
   WHERE date_start_plan BETWEEN date('now') AND date('now', '+30 days')  ← правильно

3. ПОИСК ПРОЕКТА — всегда используй py_lower(p.name) LIKE '%ключевое_слово%'.
   ПРЕДУПРЕЖДЕНИЕ: Если ключевое слово короткое или общее (например «северный», «восток»),
   оно может совпасть с НЕСКОЛЬКИМИ проектами. Это даст агрегированные данные сразу по нескольким
   объектам, что НЕВЕРНО.
   Алгоритм:
     а) Сначала вызови list_projects и убедись, что ключевое слово однозначно.
     б) Если два проекта содержат похожее слово — используй более длинную часть названия
        или project_id напрямую (WHERE p.id = X).
     Пример: «ТЦ Северный» и «Жилой комплекс Северный» оба содержат «северный».
     Правильно: WHERE py_lower(p.name) LIKE '%тц%северный%'  ← добавь «тц»
     Или:       WHERE p.id = 1  ← используй ID напрямую

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

-- Задачи в работе (исключаем терминальные стадии + страховка по NULL stage_name):
SELECT t.phase, t.task_name, t.stage_name, t.completion_pct,
       t.date_start_actual, t.date_end_plan
FROM tasks t
JOIN projects p ON p.id = t.project_id
WHERE py_lower(p.name) LIKE '%питер%'
  AND (
        (t.stage_name IS NOT NULL AND t.stage_name NOT IN ('Новая', 'Завершена'))
     OR (t.stage_name IS NULL AND t.completion_pct > 0 AND t.completion_pct < 100)
     OR (t.stage_name IS NULL AND t.date_start_actual IS NOT NULL AND t.date_start_actual <> ''
                              AND (t.date_end_actual IS NULL OR t.date_end_actual = ''))
  )
ORDER BY t.date_end_plan;

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

-- Позиции закупок с перерасходом цены (price > price_plan в items_json):
SELECT pr.id, pr.status, p.name AS project, pr.created_at,
       ji.value->>'material_name'                                                    AS material,
       ROUND(CAST(ji.value->>'qty'        AS REAL), 2)                              AS qty,
       ROUND(CAST(ji.value->>'price'      AS REAL), 2)                              AS price_actual,
       ROUND(CAST(ji.value->>'price_plan' AS REAL), 2)                              AS price_plan,
       ROUND((CAST(ji.value->>'price' AS REAL) - CAST(ji.value->>'price_plan' AS REAL))
             / CAST(ji.value->>'price_plan' AS REAL) * 100, 1)                      AS dev_pct,
       ROUND((CAST(ji.value->>'price' AS REAL) - CAST(ji.value->>'price_plan' AS REAL))
             * CAST(ji.value->>'qty' AS REAL))                                       AS overspend_rub
FROM purchase_requests pr
JOIN projects p ON p.id = pr.project_id
JOIN json_each(pr.items_json) ji
WHERE py_lower(p.name) LIKE '%питер%'
  AND CAST(ji.value->>'price_plan' AS REAL) > 0
  AND CAST(ji.value->>'price'      AS REAL) > CAST(ji.value->>'price_plan' AS REAL)
ORDER BY dev_pct DESC;

-- Отклонение средней цены закупки от плановой (из таблицы materials):
SELECT m.material_name, m.unit,
       SUM(m.qty_bought)                                                            AS qty_bought,
       ROUND(AVG(CASE WHEN m.price_plan   > 0 THEN m.price_plan   END), 2)         AS price_plan,
       ROUND(AVG(CASE WHEN m.price_actual > 0 THEN m.price_actual END), 2)         AS price_actual,
       ROUND((AVG(CASE WHEN m.price_actual > 0 THEN m.price_actual END) -
              AVG(CASE WHEN m.price_plan   > 0 THEN m.price_plan   END))
             / NULLIF(AVG(CASE WHEN m.price_plan > 0 THEN m.price_plan END), 0)
             * 100, 1)                                                              AS dev_pct,
       ROUND((AVG(CASE WHEN m.price_actual > 0 THEN m.price_actual END) -
              AVG(CASE WHEN m.price_plan   > 0 THEN m.price_plan   END))
             * SUM(m.qty_bought))                                                   AS overspend_rub
FROM materials m
JOIN projects p ON p.id = m.project_id
WHERE py_lower(p.name) LIKE '%питер%'
  AND m.price_plan > 0 AND m.price_actual > 0
  AND m.price_actual > m.price_plan
GROUP BY m.material_name, m.unit
ORDER BY dev_pct DESC;

-- Перерасход по материалам из budget_phases (работает даже если materials таблица пуста):
SELECT bp.phase_name,
       ROUND(bp.materials_plan, 0)   AS mat_plan,
       ROUND(bp.materials_actual, 0) AS mat_actual,
       ROUND((bp.materials_actual - bp.materials_plan) * 100.0
             / NULLIF(bp.materials_plan, 0), 1) AS dev_pct,
       ROUND(bp.materials_actual - bp.materials_plan, 0) AS overspend_rub
FROM budget_phases bp
JOIN projects p ON p.id = bp.project_id
WHERE py_lower(p.name) LIKE '%питер%'
  AND bp.materials_plan > 0
  AND bp.materials_actual > bp.materials_plan
ORDER BY dev_pct DESC;

-- Мягкий сигнал: материал расходуется быстрее, чем выполняются задачи (порог +15%):
SELECT m.material_name, m.unit,
       ROUND(SUM(m.qty_plan), 2)                                                     AS qty_plan,
       ROUND(SUM(m.qty_consumed), 2)                                                 AS qty_consumed,
       ROUND(SUM(m.qty_consumed) * 100.0 / NULLIF(SUM(m.qty_plan), 0), 1)           AS consumed_pct,
       ROUND(AVG(t.completion_pct), 1)                                               AS task_done_pct,
       COUNT(DISTINCT t.task_name)                                                   AS tasks_total,
       COUNT(DISTINCT CASE WHEN t.completion_pct < 100 THEN t.task_name END)         AS tasks_remaining,
       COUNT(DISTINCT CASE WHEN t.stage_name NOT IN ('Новая', 'Завершена')
             THEN t.task_name END)                                                   AS tasks_active
FROM materials m
JOIN tasks t ON t.project_id = m.project_id
           AND t.phase = m.phase
           AND t.task_name = m.task_name
JOIN projects p ON p.id = m.project_id
WHERE py_lower(p.name) LIKE '%питер%'
  AND m.qty_plan > 0
GROUP BY m.material_name, m.unit
HAVING consumed_pct > task_done_pct + 15
ORDER BY (consumed_pct - task_done_pct) DESC;
"""
