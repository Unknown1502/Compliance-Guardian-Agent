import { useEffect, useRef } from "react";
import { animate, useMotionValue, useTransform, motion } from "framer-motion";

export function AnimatedNumber({
  value,
  className,
  format,
}: {
  value: number;
  className?: string;
  format?: (n: number) => string;
}) {
  const motionVal = useMotionValue(0);
  const rounded = useTransform(motionVal, (v) => (format ? format(v) : Math.round(v).toString()));
  const first = useRef(true);

  useEffect(() => {
    const controls = animate(motionVal, value, {
      duration: first.current ? 0.9 : 0.6,
      ease: [0.16, 1, 0.3, 1],
    });
    first.current = false;
    return controls.stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <motion.span className={className}>
      {rounded}
    </motion.span>
  );
}
