interface ConfirmActionCardProps {
  title: string;
  fields: Array<{ label: string; value: string }>;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}

export function ConfirmActionCard({
  title,
  fields,
  onConfirm,
  onCancel,
  busy = false,
}: ConfirmActionCardProps) {
  return (
    <div
      className="mt-3 bg-surface border border-border rounded-card p-4 text-ink"
      data-testid="confirm-action-card"
    >
      <h4 className="font-medium text-sm mb-3">{title}</h4>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {fields.map((f) => (
          <div key={f.label} className="contents">
            <dt className="text-muted">{f.label}:</dt>
            <dd className="text-ink">{f.value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex gap-2 mt-4">
        <button
          type="button"
          disabled={busy}
          onClick={onConfirm}
          data-testid="confirm-btn"
          className="flex-1 bg-accent text-white rounded-pill text-sm font-medium py-2 hover:bg-accent/90 disabled:opacity-50"
        >
          {busy ? "Выполняется…" : "Подтвердить"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onCancel}
          data-testid="cancel-btn"
          className="flex-1 bg-bg border border-border text-ink rounded-pill text-sm font-medium py-2 hover:bg-border disabled:opacity-50"
        >
          Отмена
        </button>
      </div>
    </div>
  );
}
