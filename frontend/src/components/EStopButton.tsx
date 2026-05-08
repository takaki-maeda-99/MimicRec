import { useEstop, useClearEstop } from "../api/queries.ts";
import { Button } from "./ui/button";

export default function EStopButton() {
  const estop = useEstop();
  const clear = useClearEstop();

  return (
    <div className="border-2 border-brand-error bg-brand-error/10 rounded-md p-3 flex items-center gap-3">
      <Button
        variant="primary"
        className="!bg-brand-error !text-on-dark hover:!bg-brand-error/90 font-bold text-lg px-6 py-3 shadow"
        onClick={() => estop.mutate()}
        disabled={estop.isPending}
      >
        ⏻ E-STOP
      </Button>
      <Button
        variant="link"
        className="text-sm text-brand-error underline"
        onClick={() => clear.mutate()}
        disabled={clear.isPending}
      >
        clear E-stop
      </Button>
      {estop.isError && <span className="text-xs text-brand-error">estop failed</span>}
      {clear.isError && <span className="text-xs text-brand-error">clear failed</span>}
    </div>
  );
}
