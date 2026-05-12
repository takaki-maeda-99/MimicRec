import { useEstop, useClearEstop } from "../api/queries.ts";
import { cn } from "../lib/utils";

/**
 * Sidebar-fit safety affordance. Renders a single 64px panel with double
 * red border. "clear E-stop" is a small inline secondary link that only
 * appears after a stop has fired (estop.isSuccess or clear is needed).
 */
export default function EStopButton() {
  const estop = useEstop();
  const clear = useClearEstop();
  const showClear = estop.isSuccess || clear.isError;

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={() => estop.mutate()}
        disabled={estop.isPending}
        className={cn(
          "h-16 w-full flex flex-col items-center justify-center gap-0.5",
          "rounded-md border-2 border-double border-brand-error bg-brand-error/10",
          "text-brand-error transition-colors",
          "hover:bg-brand-error/15 disabled:opacity-60 disabled:cursor-not-allowed",
        )}
        aria-label="Emergency stop"
      >
        <span className="font-mono text-micro-uppercase tracking-[0.32em] opacity-70">
          EMERGENCY
        </span>
        <span className="font-bold text-body-md-medium tracking-wider leading-none">
          E-STOP
        </span>
      </button>
      {showClear && (
        <button
          type="button"
          onClick={() => clear.mutate()}
          disabled={clear.isPending}
          className="text-caption text-brand-error underline underline-offset-2 self-center"
        >
          clear E-stop
        </button>
      )}
      {estop.isError && (
        <span className="text-caption text-brand-error text-center">estop failed</span>
      )}
      {clear.isError && (
        <span className="text-caption text-brand-error text-center">clear failed</span>
      )}
    </div>
  );
}
