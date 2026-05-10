import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface RecordFormDraft {
  mode: "teleop" | "hand_teach";
  robot: string;
  teleop: string;
  mapper: string;
  selectedCams: string[];
  selectedGopros: string[];
  dataset: string;
  task: string;
  fps: number;
  autoCycle: boolean;
  autoDurationSec: number;
  autoReviewSec: number;
  previewEnabled: boolean;
}

interface RecordFormStore extends RecordFormDraft {
  set: (patch: Partial<RecordFormDraft>) => void;
  reset: () => void;
}

const DEFAULTS: RecordFormDraft = {
  mode: "teleop",
  robot: "",
  teleop: "",
  mapper: "",
  selectedCams: [],
  selectedGopros: [],
  dataset: "",
  task: "",
  fps: 30,
  autoCycle: false,
  autoDurationSec: 10,
  autoReviewSec: 3,
  previewEnabled: true,
};

export const useRecordFormStore = create<RecordFormStore>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      set: (patch) => set(patch),
      reset: () => set(DEFAULTS),
    }),
    { name: "mimicrec-record-form" },
  ),
);
