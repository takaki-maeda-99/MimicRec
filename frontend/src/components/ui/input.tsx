import { cn } from "../../lib/utils";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

export function Input({ className, ...props }: InputProps) {
  return (
    <input
      className={cn(
        "flex h-10 w-full rounded-md border border-hairline bg-canvas px-md text-body-md text-ink placeholder:text-stone",
        "focus-visible:outline-none focus-visible:border-2 focus-visible:border-ink",
        "disabled:cursor-not-allowed disabled:bg-surface disabled:text-muted",
        className,
      )}
      {...props}
    />
  );
}
