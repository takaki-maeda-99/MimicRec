import { cn } from "../../lib/utils";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "base" | "feature";
}

export function Card({ className, variant = "base", ...props }: CardProps) {
  const variants = {
    base: "rounded-lg border border-hairline bg-canvas p-lg",
    feature: "rounded-lg bg-surface p-xl",
  } as const;
  return <div className={cn(variants[variant], className)} {...props} />;
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1.5 mb-md", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-heading-5 text-ink", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("text-body-sm text-charcoal", className)} {...props} />;
}
