import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { motion } from "framer-motion";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ToastProvider } from "./context/ToastContext";
import { Login } from "./components/Login";
import { Layout } from "./components/Layout";
import { LandingPage } from "./views/LandingPage";
import { TaskQueue } from "./views/TaskQueue";
import { UploadView } from "./views/UploadView";
import { CheckDetail } from "./views/CheckDetail";
import { AuditLog } from "./views/AuditLog";
import { ReportsView } from "./views/ReportsView";
import { BillingView } from "./views/BillingView";
import { RulesetsView } from "./views/RulesetsView";
import { SettingsView } from "./views/SettingsView";
import { TeamView } from "./views/TeamView";

function SplashScreen() {
  return (
    <div className="grid min-h-screen place-items-center bg-bg dark:bg-slate-950">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4 }}
        className="flex flex-col items-center gap-3"
      >
        <div className="flex items-baseline gap-[3px]">
          <span className="text-[17px] font-bold tracking-tight text-ink dark:text-slate-50">
            ComplianceGuardian
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

  if (!session) {
    return (
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<Login initialMode="signin" />} />
        <Route path="/signup" element={<Login initialMode="signup" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<TaskQueue />} />
        <Route path="upload" element={<UploadView />} />
        <Route path="checks/:checkId" element={<CheckDetail />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="reports" element={<ReportsView />} />
        <Route path="rulesets" element={<RulesetsView />} />
        <Route path="billing" element={<BillingView />} />
        <Route path="team" element={<TeamView />} />
        <Route path="settings" element={<SettingsView />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
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
