import type { ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

type ButtonVariant = "primary" | "secondary" | "ghost" | "stage";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
};

// Booth / authoring buttons live on light surfaces; "stage" is for play surfaces.
const variants: Record<ButtonVariant, string> = {
  primary:
    "bg-midnight text-white hover:bg-midnightHover disabled:bg-softline disabled:text-steel",
  secondary:
    "bg-chip text-midnight hover:bg-chipHover disabled:bg-pale disabled:text-steel",
  ghost: "bg-transparent text-midnight hover:bg-chip disabled:text-steel",
  stage:
    "bg-stagegold text-midnight font-bold hover:bg-stagegoldHover disabled:bg-white/20 disabled:text-white/40",
};

export function Button({ className, variant = "primary", ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-electric focus:ring-offset-2",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
