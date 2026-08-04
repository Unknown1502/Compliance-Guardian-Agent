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
      <div className="grid h-12 w-12 place-items-center rounded-full bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
        <Icon size={22} strokeWidth={1.75} />
      </div>
      <div>
        <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{title}</p>
        {description && (
          <p className="mx-auto mt-1 max-w-sm text-sm text-slate-400 dark:text-slate-500">
            {description}
          </p>
        )}
      </div>
      {action}
    </motion.div>
  );
}
