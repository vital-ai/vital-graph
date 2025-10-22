/**
 * Hook for managing WebSocket connection with JWT authentication.
 * 
 * This hook automatically connects/disconnects the WebSocket based on
 * authentication status and handles token refresh for WebSocket connections.
 */

import { useEffect, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { webSocketService } from '../services/WebSocketService';

export const useAuthenticatedWebSocket = () => {
  const { isAuthenticated, token } = useAuth();

  // Connect WebSocket when authenticated
  const connectWebSocket = useCallback(async () => {
    if (isAuthenticated && token) {
      console.log('🔌 Connecting WebSocket with JWT authentication...');
      
      try {
        const success = await webSocketService.connect(token);
        if (success) {
          console.log('✅ WebSocket connected successfully');
        } else {
          console.error('❌ Failed to connect WebSocket');
        }
      } catch (error) {
        console.error('❌ WebSocket connection error:', error);
      }
    }
  }, [isAuthenticated, token]);

  // Disconnect WebSocket when not authenticated
  const disconnectWebSocket = useCallback(async () => {
    console.log('🔌 Disconnecting WebSocket...');
    await webSocketService.disconnect();
  }, []);

  // Auto-connect/disconnect based on auth status
  useEffect(() => {
    if (isAuthenticated && token) {
      connectWebSocket();
    } else {
      disconnectWebSocket();
    }

    // Cleanup on unmount
    return () => {
      disconnectWebSocket();
    };
  }, [isAuthenticated, token, connectWebSocket, disconnectWebSocket]);

  return {
    connectWebSocket,
    disconnectWebSocket,
    isAuthenticated,
  };
};

export default useAuthenticatedWebSocket;
