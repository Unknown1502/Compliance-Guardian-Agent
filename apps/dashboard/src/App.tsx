import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Login } from "./components/Login";
import { Layout } from "./components/Layout";
import { TaskQueue } from "./views/TaskQueue";
import { UploadView } from "./views/UploadView";
import { CheckDetail } from "./views/CheckDetail";
import { AuditLog } from "./views/AuditLog";
import { ReportsView } from "./views/ReportsView";

function Gate() {
  const { session, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen grid place-items-center text-slate-400">
        Loading…
      </div>
    );
  }
  if (!session) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<TaskQueue />} />
        <Route path="upload" element={<UploadView />} />
        <Route path="checks/:checkId" element={<CheckDetail />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="reports" element={<ReportsView />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  );
}
