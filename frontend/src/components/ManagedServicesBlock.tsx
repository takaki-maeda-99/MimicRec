import { useState } from "react";
import type { ManagedServiceStatus } from "../api/types";
import { useManagedServices, useServiceAction } from "../api/queries";
import { useSessionStore } from "../state/session-store";
import { ApiError } from "../api/client";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { SectionMark } from "./ui/section-mark";

type ServiceAction = "start" | "stop" | "restart" | "clear-fault";

export function ManagedServicesBlock() {
  const { data: services = [], isLoading, error, refetch } = useManagedServices();
  const mutation = useServiceAction();
  const sessionState = useSessionStore((s) => s.state);
  const [actionError, setActionError] = useState<string | null>(null);
  const sessionActive = sessionState !== "idle";

  const run = async (service: ManagedServiceStatus, action: ServiceAction) => {
    let confirmed = false;
    if (action === "clear-fault") {
      confirmed = window.confirm(
        "Clear hardware faults and re-enable every reBotArm motor? " +
        "Support the arm, clear the workspace, and make sure the gripper cannot pinch anything. " +
        "The daemon will resume in gravity compensation mode.",
      );
      if (!confirmed) return;
    } else if (service.safety_critical && (action === "start" || action === "restart")) {
      confirmed = window.confirm(
        `${service.label} will connect to physical hardware. ` +
        "Confirm that the workspace is clear, the mechanism is supported, and no one can be pinched.",
      );
      if (!confirmed) return;
    } else if (action === "stop" || action === "restart") {
      if (!window.confirm(`${action === "stop" ? "Stop" : "Restart"} ${service.label}?`)) return;
    }

    setActionError(null);
    try {
      await mutation.mutateAsync({
        serviceId: service.id,
        action,
        confirmHardwareReady: confirmed,
      });
      if (action === "clear-fault") {
        window.alert("Motor faults cleared. reBotArm is in gravity compensation mode.");
      }
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <section className="flex flex-col gap-md">
      <header className="flex items-baseline gap-md">
        <SectionMark code="§04.A" name="Managed services" />
        <span className="flex-1 h-px bg-hairline-soft" />
        <Button variant="secondary" size="sm" onClick={() => refetch()} disabled={isLoading}>
          {isLoading ? "Refreshing…" : "Refresh"}
        </Button>
      </header>

      <div className="rounded-md border border-hairline bg-canvas divide-y divide-hairline-soft">
        {services.map((service) => {
          const active = service.active_state === "active";
          const ready = active && service.endpoint_ready;
          const unavailable = !service.installed || !service.control_enabled || service.conflict;
          const controlsDisabled = unavailable || sessionActive || mutation.isPending;
          return (
            <div key={service.id} className="p-md flex flex-col md:flex-row md:items-center gap-md">
              <span
                aria-hidden
                className={`w-2 h-2 rounded-full shrink-0 ${
                  ready ? "bg-brand-green" : service.active_state === "failed" ? "bg-brand-error" : active ? "bg-brand-warn" : "bg-muted"
                }`}
              />
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-xs">
                  <span className="text-body-sm-medium text-ink">{service.label}</span>
                  <Badge variant={ready ? "success" : service.active_state === "failed" ? "destructive" : active ? "warning" : "outline"}>
                    {service.active_state}/{service.sub_state}
                  </Badge>
                  {active && (
                    <Badge variant={ready ? "success" : "warning"}>
                      {ready ? "endpoint ready" : "hardware connecting"}
                    </Badge>
                  )}
                  {service.safety_critical && <Badge variant="warning">hardware</Badge>}
                  {service.conflict && <Badge variant="warning">external process</Badge>}
                </div>
                <p className="text-caption text-stone mt-1">{service.description}</p>
                {service.detail && <p className="text-caption text-brand-warn mt-1">{service.detail}</p>}
              </div>
              <div className="flex items-center gap-xs shrink-0">
                {!active ? (
                  <Button size="sm" onClick={() => run(service, "start")} disabled={controlsDisabled}>
                    Start
                  </Button>
                ) : (
                  <>
                    {service.id === "rebotarm" && (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => run(service, "clear-fault")}
                        disabled={controlsDisabled || !ready}
                      >
                        Clear fault
                      </Button>
                    )}
                    <Button variant="secondary" size="sm" onClick={() => run(service, "restart")} disabled={controlsDisabled}>
                      Restart
                    </Button>
                    <Button variant="destructive" size="sm" onClick={() => run(service, "stop")} disabled={controlsDisabled}>
                      Stop
                    </Button>
                  </>
                )}
              </div>
            </div>
          );
        })}
        {!isLoading && services.length === 0 && (
          <p className="p-md text-body-sm text-stone">No managed services reported.</p>
        )}
      </div>

      {sessionActive && (
        <p className="text-caption text-brand-warn">
          Service changes are locked while a recording, replay, or inference session is active.
        </p>
      )}
      {!services.every((service) => service.control_enabled) && services.length > 0 && (
        <p className="text-caption text-stone">
          Install once with <code className="font-mono text-code-inline text-charcoal">bash scripts/install_user_services.sh</code>, then restart the backend.
        </p>
      )}
      {(actionError || error) && (
        <p role="alert" className="text-caption text-brand-error">
          {actionError ?? `Service status unavailable: ${String(error)}`}
        </p>
      )}
    </section>
  );
}
