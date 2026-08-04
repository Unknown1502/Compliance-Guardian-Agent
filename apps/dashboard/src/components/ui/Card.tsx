import { motion, type HTMLMotionProps } from "framer-motion";
import { cn } from "../../lib/cn";

interface CardProps extends HTMLMotionProps<"div"> {
  hover?: boolean;
  padded?: boolean;
}

export function Card({ className, hover, padded = true, children, ...props }: CardProps) {
  return (
    <motion.div
      className={cn(
        "rounded-2xl border border-slate-200/80 bg-white shadow-soft dark:border-slate-800 dark:bg-slate-900",
        padded && "p-5 sm:p-6",
        hover && "transition-shadow hover:shadow-soft-md",
        className,
      )}
      {...props}
    >
      {children}
    </motion.div>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-4 flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h3>
        {subtitle && (
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}
