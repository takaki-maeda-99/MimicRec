import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Layout from "./components/Layout";
import { ErrorBoundary } from "./components/ErrorBoundary";
import DatasetsPage from "./pages/DatasetsPage";
import RecordPage from "./pages/RecordPage";
import EpisodesPage from "./pages/EpisodesPage";
import ReplayPage from "./pages/ReplayPage";
import SettingsPage from "./pages/SettingsPage";
import { InferencePage } from "./pages/InferencePage";
import MockIndex from "./pages/mocks/MockIndex";
import MockMissionControl from "./pages/mocks/MockMissionControl";
import MockEditorial from "./pages/mocks/MockEditorial";
import MockNotebook from "./pages/mocks/MockNotebook";

const queryClient = new QueryClient();

const ROUTER_BASENAME = import.meta.env.BASE_URL.replace(/\/$/, "");

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={ROUTER_BASENAME}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<Navigate to="/datasets" replace />} />
              <Route path="/datasets" element={<DatasetsPage />} />
              <Route path="/record" element={<RecordPage />} />
              <Route path="/datasets/:ds/episodes" element={<EpisodesPage />} />
              <Route path="/datasets/:ds/episodes/:idx/replay" element={<ReplayPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/inference" element={<InferencePage />} />
            </Route>
            {/* Layout-comparison mocks (no shell — each mock owns the screen) */}
            <Route path="/mocks" element={<MockIndex />} />
            <Route path="/mocks/mission-control" element={<MockMissionControl />} />
            <Route path="/mocks/editorial" element={<MockEditorial />} />
            <Route path="/mocks/notebook" element={<MockNotebook />} />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
