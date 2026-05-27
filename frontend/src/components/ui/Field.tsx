import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-md border border-softline bg-white px-3 text-base text-midnight placeholder:text-steel outline-none transition focus:border-electric focus:ring-2 focus:ring-softblue",
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-32 w-full rounded-md border border-softline bg-white px-3 py-3 text-base leading-6 text-midnight placeholder:text-steel outline-none transition focus:border-electric focus:ring-2 focus:ring-softblue",
        className,
      )}
      {...props}
    />
  );
}
