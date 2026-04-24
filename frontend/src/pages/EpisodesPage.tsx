import { useParams } from "react-router-dom";

export default function EpisodesPage() {
  const { ds } = useParams<{ ds: string }>();
  return (
    <div className="p-6">
      <h2 className="text-2xl font-bold mb-4">Episodes — {ds}</h2>
      <p className="text-gray-500">Episode table coming next.</p>
    </div>
  );
}
