import { useState } from "react";
import { Link } from "react-router-dom";
import { useDatasets, useCreateDataset } from "../api/queries";

export default function DatasetsPage() {
  const { data: datasets, isLoading } = useDatasets();
  const createMutation = useCreateDataset();
  const [name, setName] = useState("");
  const [fps, setFps] = useState(30);

  const handleCreate = () => {
    if (!name.trim()) return;
    createMutation.mutate(
      { name: name.trim(), fps, joint_names: [], camera_names: [] },
      { onSuccess: () => setName("") }
    );
  };

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-2xl font-bold mb-6">Datasets</h2>

      {/* Create form */}
      <div className="flex gap-3 mb-6 items-end">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my_dataset"
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">FPS</label>
          <input
            type="number"
            className="border border-gray-300 rounded-md px-3 py-2 text-sm w-20"
            value={fps}
            onChange={(e) => setFps(Number(e.target.value))}
          />
        </div>
        <button
          className="bg-blue-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          onClick={handleCreate}
          disabled={createMutation.isPending || !name.trim()}
        >
          Create
        </button>
      </div>

      {/* Dataset list */}
      {isLoading ? (
        <p className="text-gray-500">Loading...</p>
      ) : !datasets?.length ? (
        <p className="text-gray-500">No datasets yet. Create one above.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-gray-500">
              <th className="pb-2 font-medium">Name</th>
              <th className="pb-2 font-medium">Episodes</th>
              <th className="pb-2 font-medium">Frames</th>
              <th className="pb-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((ds) => (
              <tr key={ds.name} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-3">
                  <Link
                    to={`/datasets/${ds.name}/episodes`}
                    className="text-blue-600 hover:underline font-medium"
                  >
                    {ds.name}
                  </Link>
                </td>
                <td className="py-3 text-gray-600">{ds.num_episodes}</td>
                <td className="py-3 text-gray-600">{ds.total_frames}</td>
                <td className="py-3">
                  <a
                    href={`/api/datasets/${ds.name}/archive`}
                    className="text-sm text-gray-600 hover:text-gray-900"
                    download
                  >
                    Download
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
