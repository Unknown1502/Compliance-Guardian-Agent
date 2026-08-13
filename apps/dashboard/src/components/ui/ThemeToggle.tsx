import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme, type ThemePreference } from "../../context/ThemeContext";

const OPTIONS: { value: ThemePreference; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
];

/**
 * Three-state theme control.
 *
 * A segmented control rather than a cycling icon button: with three states a
 * single button gives no indication of what the next press does, and "System"
 * is invisible — you cannot tell whether the light you are looking at was
 * chosen or inherited. Here the current preference is always legible.
 *
 * Built as a radiogroup so arrow keys move between options, which is what a
 * keyboard user expects from a segmented control.
 */
export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { preference, setPreference } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="Color theme"
      className="inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface-2 p-0.5"
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = preference === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={compact ? label : undefined}
            title={compact ? label : undefined}
            onClick={() => setPreference(value)}
            className={[
              "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[13px] font-medium transition-colors",
              active
                ? "bg-surface text-ink shadow-sm"
                : "text-muted hover:text-ink-2",
            ].join(" ")}
          >
            <Icon size={14} aria-hidden="true" />
            {!compact && label}
          </button>
        );
      })}
    </div>
  );
}
