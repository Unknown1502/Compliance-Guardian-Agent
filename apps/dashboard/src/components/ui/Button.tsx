import { forwardRef } from "react";
import { motion, type HTMLMotionProps } from "framer-motion";
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success" | "outline";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends Omit<HTMLMotionProps<"button">, "ref" | "children"> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: React.ReactNode;
  children?: React.ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-600 text-white shadow-soft hover:bg-brand-700 disabled:hover:bg-brand-600 dark:bg-brand-500 dark:hover:bg-brand-400",
  secondary:
    "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700",
  outline:
    "border border-slate-300 text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800",
  ghost:
    "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
  danger:
    "bg-status-critical text-white shadow-soft hover:bg-red-600 disabled:hover:bg-status-critical",
  success:
    "bg-status-good text-white shadow-soft hover:bg-green-700 disabled:hover:bg-status-good",
};

const SIZES: Record<Size, string> = {
  sm: "text-xs px-3 py-1.5 gap-1.5 rounded-lg",
  md: "text-sm px-4 py-2 gap-2 rounded-lg",
  lg: "text-sm px-5 py-2.5 gap-2 rounded-xl",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant = "primary", size = "md", loading, icon, disabled, children, ...props },
    ref,
  ) => {
    return (
      <motion.button
        ref={ref}
        whileHover={disabled || loading ? undefined : { y: -1 }}
        whileTap={disabled || loading ? undefined : { scale: 0.97 }}
        transition={{ type: "spring", stiffness: 500, damping: 30 }}
        disabled={disabled || loading}
        className={cn(
          "inline-flex select-none items-center justify-center font-medium transition-colors focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
          VARIANTS[variant],
          SIZES[size],
          className,
        )}
        {...props}
      >
        {loading ? (
          <Loader2 size={size === "sm" ? 13 : 15} className="animate-spin" />
        ) : (
          icon
        )}
        {children}
      </motion.button>
    );
  },
);
Button.displayName = "Button";
