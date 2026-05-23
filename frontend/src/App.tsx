import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import { SidePanelProvider } from "./contexts/SidePanelContext";
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { CreateProjectPage } from "./pages/CreateProjectPage";
import { AiPage } from "./pages/AiPage";
import { ForemanPage } from "./pages/ForemanPage";
import { ProcurementPage } from "./pages/ProcurementPage";
import { UploadPage } from "./pages/UploadPage";

export default function App() {
  return (
    <AuthProvider>
      <SidePanelProvider>
        <BrowserRouter>
          <AppShell>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/projects/new" element={<CreateProjectPage />} />
              <Route path="/projects/:id" element={<ProjectDetailPage />} />
              <Route path="/ai" element={<AiPage />} />
              <Route path="/foreman-report" element={<ForemanPage />} />
              <Route path="/procurement" element={<ProcurementPage />} />
              <Route path="/upload" element={<UploadPage />} />
            </Routes>
          </AppShell>
        </BrowserRouter>
      </SidePanelProvider>
    </AuthProvider>
  );
}
