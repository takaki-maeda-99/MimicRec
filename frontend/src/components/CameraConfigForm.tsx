import { useEffect, useMemo, useState } from "react";
import { Button } from "./ui/button";
import {
  fetchCameraCapabilities,
  saveCameraConfig,
  type FormatCaps,
} from "../api/cameras";

interface Props {
  name: string;
  currentContent: Record<string, unknown>;
  onSave: (validationSkipped: boolean) => void;
  onCancel: () => void;
}

const OPENCV_TARGET = "mimicrec.cameras.opencv_camera.OpenCVCamera";

export function CameraConfigForm({ name, currentContent, onSave, onCancel }: Props) {
  const [deviceId, setDeviceId] = useState<number>(
    Number(currentContent.device_id ?? 0),
  );
  const [capabilities, setCapabilities] = useState<FormatCaps[]>([]);
  const [loadingCaps, setLoadingCaps] = useState(false);
  const [capsError, setCapsError] = useState<string | null>(null);

  const [pixelFormat, setPixelFormat] = useState<string>(
    String(currentContent.pixel_format ?? ""),
  );
  const [width, setWidth] = useState<number>(Number(currentContent.width ?? 640));
  const [height, setHeight] = useState<number>(Number(currentContent.height ?? 480));
  const [captureFps, setCaptureFps] = useState<number>(
    Number(currentContent.capture_fps ?? 0),
  );

  const [staleWarning, setStaleWarning] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Fetch capabilities whenever deviceId changes.
  useEffect(() => {
    setLoadingCaps(true);
    setCapsError(null);
    fetchCameraCapabilities(deviceId)
      .then((caps) => {
        setCapabilities(caps);

        if (caps.length === 0) return;

        // Try to keep the current YAML values if they exist in the new caps.
        const formatMatch = caps.find((c) => c.fourcc === pixelFormat);
        const effectiveFormat = formatMatch ?? caps[0];
        const sizeMatch = effectiveFormat.sizes.find(
          (s) => s.width === width && s.height === height,
        );
        const effectiveSize = sizeMatch ?? effectiveFormat.sizes[0];
        const fpsMatch = effectiveSize.fps.includes(captureFps)
          ? captureFps
          : effectiveSize.fps[0];

        const allMatched =
          formatMatch !== undefined &&
          sizeMatch !== undefined &&
          effectiveSize.fps.includes(captureFps);

        if (!allMatched && (pixelFormat || width || height || captureFps)) {
          setStaleWarning(
            `⚠ Saved settings (${pixelFormat || "?"}/${width}x${height}@${captureFps}fps) ` +
              `not in this camera's current capabilities. Defaults selected — verify before saving.`,
          );
        }

        setPixelFormat(effectiveFormat.fourcc);
        setWidth(effectiveSize.width);
        setHeight(effectiveSize.height);
        setCaptureFps(fpsMatch);
      })
      .catch((e) => setCapsError(String(e)))
      .finally(() => setLoadingCaps(false));
    // Intentional: re-fetch only on deviceId change. The other state vars
    // are read as "last saved values" for mismatch detection, not as triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId]);

  // Cascading dropdown options.
  const currentFormat = useMemo(
    () => capabilities.find((c) => c.fourcc === pixelFormat),
    [capabilities, pixelFormat],
  );
  const sizeOptions = currentFormat?.sizes ?? [];
  const currentSize = useMemo(
    () => sizeOptions.find((s) => s.width === width && s.height === height),
    [sizeOptions, width, height],
  );
  const fpsOptions = currentSize?.fps ?? [];

  const onFormatChange = (newFmt: string) => {
    setPixelFormat(newFmt);
    const fmt = capabilities.find((c) => c.fourcc === newFmt);
    if (fmt && fmt.sizes.length > 0) {
      const first = fmt.sizes[0];
      setWidth(first.width);
      setHeight(first.height);
      setCaptureFps(first.fps[0] ?? 0);
    }
  };

  const onSizeChange = (idx: number) => {
    const s = sizeOptions[idx];
    if (!s) return;
    setWidth(s.width);
    setHeight(s.height);
    setCaptureFps(s.fps[0] ?? 0);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const result = await saveCameraConfig({
        name,
        content: {
          _target_: OPENCV_TARGET,
          name,
          device_id: deviceId,
          width,
          height,
          pixel_format: pixelFormat || undefined,
          capture_fps: captureFps || undefined,
        },
      });
      onSave(result.validationSkipped);
    } catch (e) {
      setSaveError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Edit cameras/{name}</h3>

      {staleWarning && (
        <div className="bg-brand-warn/10 border border-brand-warn/30 rounded p-3 text-sm text-brand-warn">
          {staleWarning}
        </div>
      )}
      {capsError && (
        <div className="bg-brand-error/10 border border-brand-error/30 rounded p-3 text-sm text-brand-error">
          Failed to load capabilities: {capsError}
        </div>
      )}
      {saveError && (
        <div className="bg-brand-error/10 border border-brand-error/30 rounded p-3 text-sm text-brand-error">
          Save failed: {saveError}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <label className="block">
          <span className="text-sm text-slate">device_id</span>
          <input
            type="number"
            min={0}
            className="mt-1 w-full border rounded px-2 py-1 font-mono text-sm"
            value={deviceId}
            onChange={(e) => setDeviceId(Number(e.target.value))}
          />
        </label>

        <label className="block">
          <span className="text-sm text-slate">pixel_format</span>
          <select
            className="mt-1 w-full border rounded px-2 py-1 text-sm"
            value={pixelFormat}
            onChange={(e) => onFormatChange(e.target.value)}
            disabled={loadingCaps || capabilities.length === 0}
          >
            {capabilities.length === 0 && <option value="">(no formats)</option>}
            {capabilities.map((c) => (
              <option key={c.fourcc} value={c.fourcc}>
                {c.fourcc} — {c.description}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-sm text-slate">resolution</span>
          <select
            className="mt-1 w-full border rounded px-2 py-1 text-sm"
            value={sizeOptions.findIndex((s) => s.width === width && s.height === height)}
            onChange={(e) => onSizeChange(Number(e.target.value))}
            disabled={loadingCaps || sizeOptions.length === 0}
          >
            {sizeOptions.length === 0 && <option value={-1}>(no sizes)</option>}
            {sizeOptions.map((s, i) => (
              <option key={`${s.width}x${s.height}`} value={i}>
                {s.width} × {s.height}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-sm text-slate">capture_fps</span>
          <select
            className="mt-1 w-full border rounded px-2 py-1 text-sm"
            value={captureFps}
            onChange={(e) => setCaptureFps(Number(e.target.value))}
            disabled={loadingCaps || fpsOptions.length === 0}
          >
            {fpsOptions.length === 0 && <option value={0}>(no fps)</option>}
            {fpsOptions.map((fps) => (
              <option key={fps} value={fps}>
                {fps} fps
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex gap-3 justify-end pt-2">
        <Button variant="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSave} disabled={saving || loadingCaps || !!capsError}>
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>
    </div>
  );
}
