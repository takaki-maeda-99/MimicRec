import { cn } from "../../lib/utils";

type VariantNew = "primary" | "secondary" | "ghost" | "link" | "iconCircular";
type VariantLegacy = "default" | "destructive" | "outline";
type Variant = VariantNew | VariantLegacy;

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "default" | "sm" | "lg";
  // Legacy aliases preserved so existing callers don't break.
  // "default" maps to "primary"; "destructive" is normalized to an internal "destructive" key
  // that produces a primary-shaped pill with text-brand-error foreground (applied internally,
  // not at the call site); "outline" maps to "secondary".
}

export function Button({
  className,
  variant = "primary",
  size = "default",
  ...props
}: ButtonProps) {
  // Normalize legacy variants
  const normalized: VariantNew | "destructive" =
    variant === "default" ? "primary" :
    variant === "outline" ? "secondary" :
    variant === "destructive" ? "destructive" :
    variant;

  const base = "inline-flex items-center justify-center font-medium transition-colors disabled:cursor-not-allowed";
  const pillPad =
    size === "sm" ? "px-sm py-1 text-caption" :
    size === "lg" ? "px-lg py-2 text-button-md" :
    "px-md py-1.5 text-button-md";

  const variants: Record<VariantNew | "destructive", string> = {
    primary:
      "rounded-full bg-primary text-on-primary " +
      pillPad +
      " hover:bg-charcoal disabled:bg-hairline disabled:text-muted",
    secondary:
      "rounded-full border border-hairline bg-transparent text-ink " +
      pillPad +
      " hover:bg-surface disabled:text-muted",
    destructive:
      "rounded-full bg-primary text-brand-error " +
      pillPad +
      " hover:bg-charcoal disabled:bg-hairline disabled:text-muted",
    // Note: ghost and iconCircular have fixed dimensions; the size prop is intentionally ignored.
    ghost:
      "rounded-md bg-transparent text-ink text-button-md px-3 py-2 hover:bg-surface disabled:text-muted",
    link:
      "bg-transparent text-ink text-body-sm-medium underline-offset-2 hover:underline p-0",
    iconCircular:
      "rounded-full bg-canvas text-ink border border-hairline w-8 h-8 hover:bg-surface",
  };

  return (
    <button
      className={cn(base, variants[normalized], className)}
      {...props}
    />
  );
}
