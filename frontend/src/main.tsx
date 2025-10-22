import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";
import axios from "axios";
import { authService } from "./services/AuthService";

// Configure axios defaults for API requests
axios.defaults.baseURL = window.location.origin;

// Set up axios interceptors to automatically include JWT tokens
axios.interceptors.request.use(
  (config) => {
    // Get current access token from AuthService
    const token = authService.getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Set up response interceptor to handle token refresh on 401 errors
axios.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      
      console.log('🔄 Received 401, attempting token refresh...');
      const refreshed = await authService.refreshAccessToken();
      
      if (refreshed) {
        // Retry the original request with new token
        const newToken = authService.getAccessToken();
        if (newToken) {
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
          return axios(originalRequest);
        }
      }
      
      // If refresh failed, redirect to login
      console.log('🚪 Token refresh failed, redirecting to login');
      window.location.href = '/login';
    }
    
    return Promise.reject(error);
  }
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
