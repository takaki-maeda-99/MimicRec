import { useEstop, useClearEstop } from "../api/queries.ts";

export default function EStopButton() {
  const estop = useEstop();
  const clear = useClearEstop();

  return (
    <div className="border-2 border-red-700 bg-red-50 rounded-md p-3 flex items-center gap-3">
      <button
        className="bg-red-600 hover:bg-red-700 text-white font-bold text-lg px-6 py-3 rounded-full shadow"
        onClick={() => estop.mutate()}
        disabled={estop.isPending}
      >
        ⏻ E-STOP
      </button>
      <button
        className="text-sm text-red-800 underline"
        onClick={() => clear.mutate()}
        disabled={clear.isPending}
      >
        clear E-stop
      </button>
      {estop.isError && <span className="text-xs text-red-700">estop failed</span>}
      {clear.isError && <span className="text-xs text-red-700">clear failed</span>}
    </div>
  );
}
