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
        "border border-slate-300 bg-white dark:border-slate-800 dark:bg-slate-900",
        padded && "p-5 sm:p-6",
        hover && "transition-colors hover:border-slate-400 dark:hover:border-slate-700",
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
        <h3 className="font-display text-[15px] font-semibold text-slate-900 dark:text-slate-50">
          {title}
        </h3>
        {subtitle && (
          <p className="mt-0.5 text-[12px] text-slate-500 dark:text-slate-400">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}

/** Page heading with a record-type eyebrow naming what this screen holds. */
export function PageHeading({
  kind,
  title,
  subtitle,
  action,
}: {
  kind: string;
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4 border-b border-slate-300 pb-4 dark:border-slate-800">
      <div>
        <p className="eyebrow">{kind}</p>
        <h2 className="mt-1.5 font-display text-[26px] font-normal leading-tight text-slate-900 dark:text-slate-50">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-1 text-[13px] text-slate-500 dark:text-slate-400">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}
