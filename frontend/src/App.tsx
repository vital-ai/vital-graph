import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { initThemeMode } from 'flowbite-react';
import { AuthProvider } from './contexts/AuthContext';
import { WebSocketProvider } from './contexts/WebSocketContext';
import { ChangeNotificationProvider } from './contexts/ChangeNotificationContext';
import ProtectedRoute from './components/auth/ProtectedRoute';
import Layout from './components/Layout';
import Login from './pages/Login';
import Home from './pages/Home';
import Spaces from './pages/Spaces';
import SpaceDetail from './pages/SpaceDetail';
import Users from './pages/Users';
import UserDetail from './pages/UserDetail';
import SPARQL from './pages/SPARQL';

// Initialize theme mode
initThemeMode();

export default function App() {
  return (
    <AuthProvider>
      <WebSocketProvider>
        <BrowserRouter>
          <ChangeNotificationProvider>
            <Routes>
          {/* Public routes */}
          <Route path="/login" element={<Login />} />
          
          {/* Protected routes - must be authenticated */}
          <Route element={<ProtectedRoute />}>
            <Route element={<Layout />}>
              <Route path="/" element={<Home />} />
              <Route path="/spaces" element={<Spaces />} />
              <Route path="/users" element={<Users />} />
              <Route path="/sparql" element={<SPARQL />} />
              <Route path="/space/:id" element={<SpaceDetail />} />
              <Route path="/user/:id" element={<UserDetail />} />
            </Route>
          </Route>
          
          {/* Redirect any other routes to home */}
          <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </ChangeNotificationProvider>
        </BrowserRouter>
      </WebSocketProvider>
    </AuthProvider>
  );
}
