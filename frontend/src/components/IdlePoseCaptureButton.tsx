import { useState } from "react";
import { useSessionStore } from "../state/session-store";
import { apiFetch } from "../api/client";
import { Button } from "./ui/button";

export default function IdlePoseCaptureButton() {
  const mode = useSessionStore((s) => s.mode);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  if (mode !== "hand_teach") return null;

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      await apiFetch("/api/session/idle-pose/capture", { method: "POST" });
      setOpen(false);
      alert("Idle pose updated.");
    } catch (e) {
      alert(`Failed to capture idle pose: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Set current pose as home
      </Button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-canvas-dark/40"
          onClick={() => !submitting && setOpen(false)}
        >
          <div
            className="bg-canvas rounded-lg border border-hairline p-xl w-[480px]"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-heading-5 text-ink mb-xs">Save idle pose</h3>
            <p className="text-body-sm text-stone mb-md">
              Save the current arm pose as the new idle position?
              This overwrites <code>configs/rebotarm/idle_pose.yaml</code>.
            </p>
            <div className="flex justify-end gap-xs">
              <Button
                variant="secondary"
                onClick={() => setOpen(false)}
                disabled={submitting}
              >
                Cancel
              </Button>
              <Button onClick={handleConfirm} disabled={submitting}>
                {submitting ? "Saving..." : "Confirm"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
