import { useEffect, useMemo, useState } from "react";

export type ItemKind = "material" | "labor" | "equipment";

interface AddItemModalProps {
  kind: ItemKind;
  phaseOptions: string[];
  taskOptions: Array<{ phase: string; task_name: string }>;
  defaultPhase?: string;
  defaultTask?: string;
  onClose: () => void;
  onSubmit: (payload: Record<string, string | number>) => Promise<void>;
}

const TITLES: Record<ItemKind, string> = {
  material: "Добавить материал",
  labor: "Добавить специальность",
  equipment: "Добавить технику",
};

const NAME_LABELS: Record<ItemKind, string> = {
  material: "Наименование материала",
  labor: "Специальность",
  equipment: "Наименование техники",
};

export function AddItemModal({
  kind,
  phaseOptions,
  taskOptions,
  defaultPhase,
  defaultTask,
  onClose,
  onSubmit,
}: AddItemModalProps) {
  const [phase, setPhase] = useState<string>(defaultPhase || phaseOptions[0] || "");
  const [taskName, setTaskName] = useState<string>(defaultTask || "");
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("шт");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filteredTasks = useMemo(
    () => taskOptions.filter((t) => !phase || t.phase === phase),
    [taskOptions, phase],
  );

  // When phase changes, pick first matching task
  useEffect(() => {
    if (filteredTasks.length > 0 && !filteredTasks.find((t) => t.task_name === taskName)) {
      setTaskName(filteredTasks[0].task_name);
    }
  }, [phase, filteredTasks, taskName]);

  const submit = async () => {
    setError(null);
    if (!phase || !taskName || !name.trim()) {
      setError("Заполните этап, задачу и наименование");
      return;
    }
    const qtyNum = parseFloat(qty) || 0;
    const priceNum = parseFloat(price) || 0;
    setSubmitting(true);
    try {
      const payload: Record<string, string | number> = {
        phase,
        task_name: taskName,
      };
      if (kind === "material") {
        payload.material_name = name.trim();
        payload.unit = unit.trim() || "шт";
        payload.qty_plan = qtyNum;
        payload.price_plan = priceNum;
      } else if (kind === "labor") {
        payload.specialty = name.trim();
        payload.hours_plan = qtyNum;
        payload.rate = priceNum;
      } else {
        payload.equipment_name = name.trim();
        payload.hours_plan = qtyNum;
        payload.price_per_hour = priceNum;
      }
      await onSubmit(payload);
      onClose();
    } catch (e) {
      setError((e as Error).message || "Ошибка");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      data-testid={`add-${kind}-modal`}
    >
      <div
        className="bg-surface border border-border rounded-card shadow-xl w-full max-w-md p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-heading text-lg text-ink">{TITLES[kind]}</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-muted hover:text-ink text-xl leading-none"
            aria-label="Закрыть"
          >
            ×
          </button>
        </div>

        <div className="flex flex-col gap-3">
          <div>
            <label className="block text-xs text-muted mb-1">Этап</label>
            <select
              value={phase}
              onChange={(e) => setPhase(e.target.value)}
              className="w-full border border-border rounded-card px-2 py-2 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
            >
              {phaseOptions.length === 0 && <option value="">— нет этапов —</option>}
              {phaseOptions.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-muted mb-1">Задача</label>
            <select
              value={taskName}
              onChange={(e) => setTaskName(e.target.value)}
              className="w-full border border-border rounded-card px-2 py-2 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
            >
              {filteredTasks.length === 0 && <option value="">— нет задач —</option>}
              {filteredTasks.map((t) => (
                <option key={`${t.phase}__${t.task_name}`} value={t.task_name}>
                  {t.task_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-muted mb-1">{NAME_LABELS[kind]}</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={
                kind === "material"
                  ? "напр. Цемент М500"
                  : kind === "labor"
                  ? "напр. Каменщик"
                  : "напр. Экскаватор"
              }
              className="w-full border border-border rounded-card px-2 py-2 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            {kind === "material" && (
              <div>
                <label className="block text-xs text-muted mb-1">Ед. изм.</label>
                <input
                  type="text"
                  value={unit}
                  onChange={(e) => setUnit(e.target.value)}
                  placeholder="кг / м² / шт"
                  className="w-full border border-border rounded-card px-2 py-2 text-sm bg-bg text-ink focus:outline-none focus:border-accent"
                />
              </div>
            )}
            <div className={kind === "material" ? "" : "col-span-1"}>
              <label className="block text-xs text-muted mb-1">
                {kind === "material" ? "Объём план" : "Часов план"}
              </label>
              <input
                type="number"
                min={0}
                step="any"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                className="w-full border border-border rounded-card px-2 py-2 text-sm bg-bg text-ink focus:outline-none focus:border-accent text-right"
              />
            </div>
            <div className={kind === "material" ? "col-span-2" : "col-span-1"}>
              <label className="block text-xs text-muted mb-1">
                {kind === "material"
                  ? "Цена за ед., ₽"
                  : kind === "labor"
                  ? "Ставка ₽/час"
                  : "Цена ₽/час"}
              </label>
              <input
                type="number"
                min={0}
                step="any"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                className="w-full border border-border rounded-card px-2 py-2 text-sm bg-bg text-ink focus:outline-none focus:border-accent text-right"
              />
            </div>
          </div>

          {error && (
            <div className="text-warning text-xs bg-warning/10 border border-warning/40 rounded-card px-3 py-2">
              {error}
            </div>
          )}

          <div className="flex gap-2 mt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 border border-border text-ink text-sm rounded-pill py-2 hover:bg-bg"
            >
              Отмена
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={submitting}
              className="flex-1 bg-accent text-white text-sm font-medium rounded-pill py-2 hover:bg-accent/90 disabled:opacity-50"
              data-testid={`add-${kind}-submit`}
            >
              {submitting ? "Сохранение…" : "Сохранить"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
