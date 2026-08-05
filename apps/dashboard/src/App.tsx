import { BrowserRouter, Routes, Route } from "react-router-dom";
import { motion } from "framer-motion";
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
        <div className="flex items-baseline gap-[3px]">
          <span className="font-display text-lg font-semibold leading-none tracking-tight text-slate-900 dark:text-slate-50">
            Compliance
          </span>
          <span className="font-display text-lg font-normal italic leading-none tracking-tight text-brand-700 dark:text-brand-300">
            Guardian
          </span>
        </div>
        <motion.div
          animate={{ scaleX: [0, 1] }}
          transition={{ duration: 1.1, repeat: Infinity, ease: "easeInOut" }}
          className="h-px w-24 origin-left bg-brand-600 dark:bg-brand-400"
        />
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
