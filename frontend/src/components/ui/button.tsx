import { cn } from "../../lib/utils";

type VariantNew = "primary" | "secondary" | "ghost" | "link" | "iconCircular";
type VariantLegacy = "default" | "destructive" | "outline";
type Variant = VariantNew | VariantLegacy;

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "default" | "xs" | "sm" | "lg";
}

export function Button({
  className,
  variant = "primary",
  size = "default",
  ...props
}: ButtonProps) {
  const normalized: VariantNew | "destructive" =
    variant === "default"
      ? "primary"
      : variant === "outline"
      ? "secondary"
      : variant === "destructive"
      ? "destructive"
      : variant;

  const base =
    "inline-flex items-center justify-center font-medium transition-colors disabled:cursor-not-allowed text-button-md";
  const pillPad =
    size === "xs"
      ? "h-7 px-2.5 text-micro"
      : size === "sm"
      ? "h-8 px-sm"
      : size === "lg"
      ? "h-10 px-lg"
      : "h-9 px-md";

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
    ghost:
      "rounded-md bg-transparent text-ink h-9 px-3 hover:bg-surface disabled:text-muted",
    link:
      "bg-transparent text-ink text-body-sm-medium underline-offset-2 hover:underline p-0",
    iconCircular:
      "rounded-full bg-canvas text-ink border border-hairline w-8 h-8 hover:bg-surface",
  };

  return <button className={cn(base, variants[normalized], className)} {...props} />;
}
