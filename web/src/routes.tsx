import { Navigate, createBrowserRouter } from "react-router-dom";
import { Layout } from "./ui/Layout";
import { DashboardView } from "./views/DashboardView";
import { SettingsView } from "./views/SettingsView";
import { TargetsView } from "./views/TargetsView";
import { MountView } from "./views/MountView";
import { PlateSolveView } from "./views/PlateSolveView";
import { CameraView } from "./views/CameraView";
import { FilterWheelView } from "./views/FilterWheelView";
import { FocuserView } from "./views/FocuserView";
import { SequenceEditorView } from "./views/SequenceEditorView";
import { SequenceRunnerView } from "./views/SequenceRunnerView";
import { GalleryView } from "./views/GalleryView";
import { SessionsView } from "./views/SessionsView";
import { SafetyView } from "./views/SafetyView";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <DashboardView /> },
      { path: "targets", element: <TargetsView /> },
      { path: "mount", element: <MountView /> },
      { path: "plate-solve", element: <PlateSolveView /> },
      { path: "camera", element: <CameraView /> },
      { path: "filter-wheel", element: <FilterWheelView /> },
      { path: "focuser", element: <FocuserView /> },
      { path: "sequences", element: <SequenceEditorView /> },
      { path: "sequences/:id", element: <SequenceRunnerView /> },
      { path: "gallery", element: <GalleryView /> },
      { path: "sessions", element: <SessionsView /> },
      { path: "sessions/:id", element: <SessionsView /> },
      { path: "safety", element: <SafetyView /> },
      { path: "settings", element: <SettingsView /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
