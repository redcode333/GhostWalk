import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import "./styles.css"
import { AppShell } from "@/components/AppShell"
import { AuthProvider, DemoEntry, RequireAuth, SignInPage, SignUpPage } from "@/pages/Auth"
import Landing from "@/pages/Landing"
import Incidents from "@/pages/Incidents"
import Incident from "@/pages/Incident"
import Learn from "@/pages/Learn"
import MapPage from "@/pages/Map"
import Proof from "@/pages/Proof"
import Settings from "@/pages/Settings"
import Onboarding from "@/pages/Onboarding"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/demo" element={<DemoEntry />} />
          <Route path="/proof" element={<DemoEntry to="/app/proof" />} />
          <Route path="/signin/*" element={<SignInPage />} />
          <Route path="/signup/*" element={<SignUpPage />} />
          <Route path="/app" element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route index element={<Navigate to="incidents" replace />} />
            <Route path="incidents" element={<Incidents />} />
            <Route path="incidents/:id" element={<Incident />} />
            <Route path="learn" element={<Learn />} />
            <Route path="learn/:id" element={<Learn />} />
            <Route path="map" element={<MapPage />} />
            <Route path="proof" element={<Proof />} />
            <Route path="settings" element={<Settings />} />
            <Route path="onboarding" element={<Onboarding />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
