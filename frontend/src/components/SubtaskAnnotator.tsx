import { useState } from "react";
import { Button } from "./ui/button";
import { apiFetch } from "../api/client";

interface Subtask {
  name: string;
  start_frame: number;
  end_frame: number;
  description: string;
}

interface AnnotateResult {
  episode_index: number;
  num_subtasks: number;
  subtasks: Subtask[];
}

interface Props {
  ds: string;
  idx: number;
  cameras: string[];
}

const DEFAULT_PROMPT = `You are analyzing a robot manipulation episode recorded as a sequence of camera images.

Divide this episode into sequential subtasks. Each subtask should be a distinct phase of the manipulation (e.g., "approach object", "grasp", "lift", "move to target", "place", "release", "retract").

Respond with a JSON array of subtasks. Each subtask has:
- "name": short name (2-4 words)
- "start_image": 0-indexed image number where this subtask begins
- "end_image": 0-indexed image number where this subtask ends (inclusive)
- "description": one sentence describing what happens

Return ONLY the JSON array, no other text.`;

export default function SubtaskAnnotator({ ds, idx, cameras }: Props) {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [camera, setCamera] = useState(cameras[0] || "front");
  const [model, setModel] = useState("google/gemma-4-E4B");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnnotateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);

  const handleAnnotate = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<AnnotateResult>(
        `/api/datasets/${ds}/episodes/${idx}/annotate`,
        {
          method: "POST",
          body: JSON.stringify({
            camera,
            model,
            sample_fps: 1.0,
            prompt: showPrompt ? prompt : null,
          }),
        }
      );
      setResult(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-3">
        <h3 className="text-sm font-medium text-gray-500">Subtask Annotation</h3>
        <select
          className="text-xs border rounded px-2 py-1"
          value={camera}
          onChange={(e) => setCamera(e.target.value)}
        >
          {cameras.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          className="text-xs border rounded px-2 py-1"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        >
          <option value="google/gemma-4-E4B">Gemma 4 E4B</option>
          <option value="google/gemma-4-E2B-it">Gemma 4 E2B-it</option>
        </select>
        <button
          className="text-xs text-blue-600 hover:text-blue-800"
          onClick={() => setShowPrompt(!showPrompt)}
        >
          {showPrompt ? "Hide Prompt" : "Edit Prompt"}
        </button>
      </div>

      {showPrompt && (
        <textarea
          className="w-full h-40 font-mono text-xs border rounded p-3 mb-3"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
      )}

      <div className="flex items-center gap-3 mb-4">
        <Button
          size="sm"
          onClick={handleAnnotate}
          disabled={loading}
        >
          {loading ? "Analyzing..." : "Annotate Subtasks"}
        </Button>
        {loading && (
          <span className="text-xs text-gray-400">
            Loading model & running inference (may take 30-60s first time)...
          </span>
        )}
      </div>

      {error && (
        <p className="text-red-600 text-sm mb-3">{error}</p>
      )}

      {result && (
        <div className="space-y-2">
          <p className="text-sm text-gray-600">
            Found <span className="font-medium">{result.num_subtasks}</span> subtasks:
          </p>
          <div className="space-y-1">
            {result.subtasks.map((st, i) => (
              <div
                key={i}
                className="flex items-start gap-3 bg-gray-50 rounded px-3 py-2 text-sm"
              >
                <span className="bg-blue-100 text-blue-700 px-2 py-0.5 rounded text-xs font-medium shrink-0">
                  {i + 1}
                </span>
                <div className="flex-1">
                  <div className="font-medium">{st.name}</div>
                  <div className="text-gray-500 text-xs">{st.description}</div>
                </div>
                <span className="text-xs text-gray-400 shrink-0">
                  frame {st.start_frame}–{st.end_frame}
                </span>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Saved to episode parquet as subtask_index + subtask_name columns.
          </p>
        </div>
      )}
    </div>
  );
}
