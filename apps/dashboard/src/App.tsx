import { Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { motion } from "framer-motion";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ToastProvider } from "./context/ToastContext";
import { Login } from "./components/Login";
import { Layout } from "./components/Layout";

// The landing page is the first thing an unauthenticated visitor sees, so it
// stays in the entry chunk — lazy-loading it would add a network round trip
// to the one view where first paint matters most.
import { LandingPage } from "./views/LandingPage";

// Everything behind auth is split per route. A signed-in user visiting the
// task queue no longer downloads the reports, trends, billing and settings
// code they may never open.
const TaskQueue = lazy(() => import("./views/TaskQueue").then((m) => ({ default: m.TaskQueue })));
const UploadView = lazy(() => import("./views/UploadView").then((m) => ({ default: m.UploadView })));
const HumanQueue = lazy(() => import("./views/HumanQueue").then((m) => ({ default: m.HumanQueue })));
const CheckDetail = lazy(() => import("./views/CheckDetail").then((m) => ({ default: m.CheckDetail })));
const AuditLog = lazy(() => import("./views/AuditLog").then((m) => ({ default: m.AuditLog })));
const ReportsView = lazy(() => import("./views/ReportsView").then((m) => ({ default: m.ReportsView })));
const TrendsView = lazy(() => import("./views/TrendsView").then((m) => ({ default: m.TrendsView })));
const WorkspaceAdmin = lazy(() =>
  import("./views/WorkspaceAdmin").then((m) => ({ default: m.WorkspaceAdmin })),
);
const RulesetsView = lazy(() => import("./views/RulesetsView").then((m) => ({ default: m.RulesetsView })));
const BillingView = lazy(() => import("./views/BillingView").then((m) => ({ default: m.BillingView })));
const TeamView = lazy(() => import("./views/TeamView").then((m) => ({ default: m.TeamView })));
const SettingsView = lazy(() => import("./views/SettingsView").then((m) => ({ default: m.SettingsView })));

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

/** Shown only for the moment a route chunk is in flight. */
function RouteFallback() {
  return (
    <div className="space-y-3">
      <div className="h-5 w-40 animate-pulse rounded bg-surface-2" />
      <div className="h-32 animate-pulse rounded-xl bg-surface-2" />
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
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<TaskQueue />} />
          <Route path="upload" element={<UploadView />} />
          <Route path="queue" element={<HumanQueue />} />
          <Route path="checks/:checkId" element={<CheckDetail />} />
          <Route path="audit" element={<AuditLog />} />
          <Route path="reports" element={<ReportsView />} />
          <Route path="trends" element={<TrendsView />} />
          <Route path="workspace" element={<WorkspaceAdmin />} />
          <Route path="rulesets" element={<RulesetsView />} />
          <Route path="billing" element={<BillingView />} />
          <Route path="team" element={<TeamView />} />
          <Route path="settings" element={<SettingsView />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
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
