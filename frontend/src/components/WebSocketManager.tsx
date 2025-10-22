/**
 * WebSocket Manager Component
 * 
 * This component handles automatic WebSocket connection management
 * based on authentication status using JWT tokens.
 */

import { useEffect } from 'react';
import useAuthenticatedWebSocket from '../hooks/useAuthenticatedWebSocket';

const WebSocketManager: React.FC = () => {
  const { isAuthenticated } = useAuthenticatedWebSocket();

  useEffect(() => {
    console.log(`🔌 WebSocket Manager: Authentication status changed to ${isAuthenticated}`);
  }, [isAuthenticated]);

  // This component doesn't render anything, it just manages WebSocket connections
  return null;
};

export default WebSocketManager;
