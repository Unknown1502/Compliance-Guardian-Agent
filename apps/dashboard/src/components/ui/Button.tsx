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
    "bg-brand-600 text-white hover:bg-brand-700 disabled:hover:bg-brand-600 dark:bg-brand-500 dark:hover:bg-brand-400",
  secondary:
    "bg-slate-200 text-slate-800 hover:bg-slate-300 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700",
  outline:
    "border border-slate-400 text-slate-700 hover:border-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-900",
  ghost:
    "text-slate-600 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-800",
  danger: "bg-oxide text-white hover:bg-[#83301F] disabled:hover:bg-oxide",
  success: "bg-brand-600 text-white hover:bg-brand-700 disabled:hover:bg-brand-600",
};

const SIZES: Record<Size, string> = {
  sm: "text-[11.5px] px-3 py-1.5 gap-1.5 tracking-[0.04em]",
  md: "text-[12.5px] px-4 py-2 gap-2 tracking-[0.04em]",
  lg: "text-[13px] px-5 py-2.5 gap-2 tracking-[0.04em]",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant = "primary", size = "md", loading, icon, disabled, children, ...props },
    ref,
  ) => {
    return (
      <motion.button
        ref={ref}
        whileTap={disabled || loading ? undefined : { scale: 0.985 }}
        transition={{ duration: 0.1 }}
        disabled={disabled || loading}
        className={cn(
          "inline-flex select-none items-center justify-center font-semibold uppercase transition-colors focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
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
