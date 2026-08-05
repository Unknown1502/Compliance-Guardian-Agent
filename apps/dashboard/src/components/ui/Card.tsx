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
        "rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
        padded && "p-5",
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
        <h3 className="text-[14px] font-semibold text-slate-900 dark:text-slate-50">{title}</h3>
        {subtitle && (
          <p className="mt-0.5 text-[12.5px] text-slate-500 dark:text-slate-400">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}

/** Page title block: bold heading, supporting line, optional right-side action. */
export function PageHeading({
  title,
  subtitle,
  action,
}: {
  /** Retained for call-site compatibility with the previous design. */
  kind?: string;
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h2 className="text-[26px] font-bold tracking-tight text-slate-900 dark:text-slate-50">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-1 text-[13.5px] text-slate-500 dark:text-slate-400">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}
