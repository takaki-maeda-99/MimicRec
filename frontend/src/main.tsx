import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

async function bootstrap() {
  if (import.meta.env.VITE_DEMO === "true") {
    const { start } = await import("./demo/setup");
    await start();
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();
