import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center"
    >
      <div className="grid h-11 w-11 place-items-center rounded-xl bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
        <Icon size={20} strokeWidth={1.75} />
      </div>
      <div>
        <p className="text-[14px] font-semibold text-slate-800 dark:text-slate-200">{title}</p>
        {description && (
          <p className="mx-auto mt-1 max-w-sm text-[13px] text-slate-500 dark:text-slate-400">
            {description}
          </p>
        )}
      </div>
      {action}
    </motion.div>
  );
}
