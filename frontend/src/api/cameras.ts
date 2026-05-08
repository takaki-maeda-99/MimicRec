import { apiFetch } from "./client";

export interface FrameSize {
  width: number;
  height: number;
  fps: number[];
}

export interface FormatCaps {
  fourcc: string;
  description: string;
  sizes: FrameSize[];
}

export const fetchCameraCapabilities = (deviceId: number) =>
  apiFetch<FormatCaps[]>(`/api/settings/devices/cameras/${deviceId}/capabilities`);

export interface SaveCameraConfigArgs {
  name: string;
  content: {
    _target_: string;
    name: string;
    device_id: number;
    width: number;
    height: number;
    pixel_format?: string;
    capture_fps?: number;
  };
}

export interface SaveCameraConfigResult {
  ok: boolean;
  validationSkipped: boolean;  // true when backend set X-Validation-Skipped
}

export async function saveCameraConfig(args: SaveCameraConfigArgs): Promise<SaveCameraConfigResult> {
  // We need access to the response headers, so do a manual fetch instead of
  // routing through apiFetch (which only returns the parsed JSON body).
  const res = await fetch(`/api/settings/configs/cameras/${args.name}`, {
    method: "PUT",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: args.content }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof body.detail === "string" ? body.detail : res.statusText);
  }
  return {
    ok: true,
    validationSkipped: res.headers.get("X-Validation-Skipped") === "device-busy",
  };
}
