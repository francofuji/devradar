import React, { Suspense, lazy } from "react";
import { Navigate, createBrowserRouter } from "react-router-dom";
import Layout from "./components/layout/Layout";
import LoadingSpinner from "./components/ui/LoadingSpinner";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Entities = lazy(() => import("./pages/Entities"));
const EntityProfile = lazy(() => import("./pages/EntityProfile"));
const Outreach = lazy(() => import("./pages/Outreach"));
const DraftViewer = lazy(() => import("./pages/DraftViewer"));
const Digest = lazy(() => import("./pages/Digest"));
const Alerts = lazy(() => import("./pages/Alerts"));
const Trends = lazy(() => import("./pages/Trends"));
const SystemHealth = lazy(() => import("./pages/SystemHealth"));
const SystemConfig = lazy(() => import("./pages/SystemConfig"));
const SystemTaxonomy = lazy(() => import("./pages/SystemTaxonomy"));
const Training = lazy(() => import("./pages/Training"));
const Logs = lazy(() => import("./pages/Logs"));
const NotFound = lazy(() => import("./pages/NotFound"));

function withSuspense(element) {
  return <Suspense fallback={<LoadingSpinner label="Cargando vista…" />}>{element}</Suspense>;
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: withSuspense(<Dashboard />) },
      { path: "entities", element: withSuspense(<Entities />) },
      { path: "entities/:handle", element: withSuspense(<EntityProfile />) },
      { path: "outreach", element: withSuspense(<Outreach />) },
      { path: "outreach/:handle", element: withSuspense(<DraftViewer />) },
      { path: "digest", element: withSuspense(<Digest />) },
      { path: "alerts", element: withSuspense(<Alerts />) },
      { path: "trends", element: withSuspense(<Trends />) },
      { path: "system/health", element: withSuspense(<SystemHealth />) },
      { path: "system/logs", element: withSuspense(<Logs />) },
      { path: "system/config", element: withSuspense(<SystemConfig />) },
      { path: "system/taxonomy", element: withSuspense(<SystemTaxonomy />) },
      { path: "training", element: withSuspense(<Training />) },
      { path: "*", element: withSuspense(<NotFound />) },
    ],
  },
]);

export default router;
