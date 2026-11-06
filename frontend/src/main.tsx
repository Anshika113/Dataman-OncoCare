import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import App from './App'
import Login from './pages/Login'
import PatientStatus from './pages/PatientStatus'
import ErrorBoundary from './components/ErrorBoundary'
import './index.css'

function Protected({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('care_token')
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          {/* The patient's own view. No session: the link token is the
              credential, and the page shows only that one visit. */}
          <Route path="/p/:token" element={<PatientStatus />} />
          {/* App owns its sub-paths: /schedule, /queue, … select the tab */}
          <Route path="/*" element={<Protected><App /></Protected>} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
)
