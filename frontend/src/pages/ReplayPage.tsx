import { useParams } from "react-router-dom";

export default function ReplayPage() {
  const { ds, idx } = useParams<{ ds: string; idx: string }>();
  return (
    <div className="p-6">
      <h2 className="text-2xl font-bold mb-4">Replay — {ds} / Episode {idx}</h2>
      <p className="text-gray-500">Replay viewer coming next.</p>
    </div>
  );
}
