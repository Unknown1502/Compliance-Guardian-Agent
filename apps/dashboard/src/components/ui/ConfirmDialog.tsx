import { AlertTriangle, type LucideIcon } from "lucide-react";
import { Modal } from "./Modal";
import { Button } from "./Button";

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  variant = "primary",
  icon: Icon = AlertTriangle,
  busy,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  variant?: "primary" | "danger" | "success";
  icon?: LucideIcon;
  busy?: boolean;
}) {
  const iconTone =
    variant === "danger"
      ? "bg-red-50 text-status-critical dark:bg-red-950/40"
      : variant === "success"
        ? "bg-green-50 text-status-good dark:bg-green-950/40"
        : "bg-brand-50 text-brand-600 dark:bg-brand-950/40";

  return (
    <Modal open={open} onClose={busy ? () => {} : onClose}>
      <div className="flex gap-4">
        <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-full ${iconTone}`}>
          <Icon size={20} strokeWidth={2} />
        </div>
        <div className="min-w-0 pt-1">
          <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">{title}</h3>
          {description && (
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>
          )}
        </div>
      </div>
      <div className="mt-6 flex justify-end gap-3">
        <Button variant="outline" size="md" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant={variant} size="md" onClick={onConfirm} loading={busy}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
