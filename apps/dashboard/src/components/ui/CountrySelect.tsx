import { useEffect, useMemo, useRef, useState } from "react";
import { Search, Check, ChevronDown } from "lucide-react";
import type { CountryRow } from "../../api/client";

const FIELD =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-[13.5px] text-slate-900 placeholder:text-slate-400 transition-colors focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100";
const LABEL_CLS = "mb-1.5 block text-[13px] font-medium text-slate-700 dark:text-slate-300";

/**
 * Searchable country combobox. value is "" for "nothing selected yet" —
 * deliberately never pre-filled, so a business must explicitly pick where it
 * operates rather than inheriting whatever the first country in the list
 * happens to be.
 */
export function CountrySelect({
  countries,
  value,
  onChange,
  disabled,
  label,
  placeholder = "Select your country",
}: {
  countries: CountryRow[];
  value: string;
  onChange: (alpha2: string) => void;
  disabled?: boolean;
  label: string;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = countries.find((c) => c.alpha2 === value) ?? null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return countries;
    return countries.filter(
      (c) => c.name.toLowerCase().includes(q) || c.alpha2.toLowerCase() === q,
    );
  }, [countries, query]);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setHighlighted(0);
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open]);

  const commit = (alpha2: string) => {
    onChange(alpha2);
    setOpen(false);
    setQuery("");
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const c = filtered[highlighted];
      if (c) commit(c.alpha2);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  };

  return (
    <div className="relative" ref={rootRef}>
      <span className={LABEL_CLS} id="country-select-label">
        {label}
      </span>
      <button
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-labelledby="country-select-label"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={`${FIELD} flex items-center justify-between text-left disabled:opacity-50`}
      >
        <span className={selected ? "" : "text-slate-400"}>
          {selected ? selected.name : placeholder}
        </span>
        <ChevronDown size={14} className="shrink-0 text-slate-400" />
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-soft-lg dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 dark:border-slate-800">
            <Search size={13} className="shrink-0 text-slate-400" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Search country..."
              className="w-full bg-transparent text-[13px] text-slate-900 placeholder:text-slate-400 focus:outline-none dark:text-slate-100"
              aria-label="Search country"
            />
          </div>
          <ul role="listbox" className="max-h-56 overflow-auto py-1">
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-[13px] text-slate-400">No matches.</li>
            )}
            {filtered.map((c, i) => (
              <li key={c.alpha2}>
                <button
                  type="button"
                  role="option"
                  aria-selected={c.alpha2 === value}
                  onClick={() => commit(c.alpha2)}
                  onMouseEnter={() => setHighlighted(i)}
                  className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-[13px] ${
                    i === highlighted
                      ? "bg-brand-50 text-brand-700 dark:bg-brand-950/40 dark:text-brand-300"
                      : "text-slate-700 dark:text-slate-300"
                  }`}
                >
                  {c.name}
                  {c.alpha2 === value && <Check size={13} className="shrink-0" />}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
