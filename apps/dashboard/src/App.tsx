import { BrowserRouter, Routes, Route } from "react-router-dom";
import { motion } from "framer-motion";
import { ShieldCheck } from "lucide-react";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ToastProvider } from "./context/ToastContext";
import { Login } from "./components/Login";
import { Layout } from "./components/Layout";
import { TaskQueue } from "./views/TaskQueue";
import { UploadView } from "./views/UploadView";
import { CheckDetail } from "./views/CheckDetail";
import { AuditLog } from "./views/AuditLog";
import { ReportsView } from "./views/ReportsView";

function SplashScreen() {
  return (
    <div className="grid min-h-screen place-items-center bg-slate-50 dark:bg-slate-950">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4 }}
        className="flex flex-col items-center gap-3"
      >
        <motion.div
          animate={{ scale: [1, 1.06, 1] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
          className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-glow-brand"
        >
          <ShieldCheck size={22} />
        </motion.div>
        <p className="text-sm text-slate-400 dark:text-slate-500">Loading ComplianceGuardian…</p>
      </motion.div>
    </div>
  );
}

function Gate() {
  const { session, loading } = useAuth();
  if (loading) return <SplashScreen />;
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
    <ThemeProvider>
      <ToastProvider>
        <BrowserRouter>
          <AuthProvider>
            <Gate />
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </ThemeProvider>
  );
}
