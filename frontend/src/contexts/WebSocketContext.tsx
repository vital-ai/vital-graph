import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { webSocketService, WebSocketResponse } from '../services/WebSocketService';
import { useAuth } from './AuthContext';

// Define types for WebSocket context
interface WebSocketState {
  isConnected: boolean;
  isConnecting: boolean;
  lastMessage: WebSocketResponse | null;
  connectionAttempts: number;
}

interface WebSocketContextType extends WebSocketState {
  sendMessage: (message: Omit<import('../services/WebSocketService').WebSocketMessage, 'token'>) => void;
  ping: () => void;
  echo: (message: string) => void;
  broadcast: (message: string) => void;
  getStatus: () => void;
}

// Create the WebSocket context with default values
const WebSocketContext = createContext<WebSocketContextType>({
  isConnected: false,
  isConnecting: false,
  lastMessage: null,
  connectionAttempts: 0,
  sendMessage: () => {},
  ping: () => {},
  echo: () => {},
  broadcast: () => {},
  getStatus: () => {},
});

// Custom hook to use the WebSocket context
export const useWebSocket = () => useContext(WebSocketContext);

interface WebSocketProviderProps {
  children: ReactNode;
}

// Provider component that wraps the app and makes WebSocket available to any child component
export const WebSocketProvider: React.FC<WebSocketProviderProps> = ({ children }) => {
  const { token, isAuthenticated } = useAuth();
  const [wsState, setWsState] = useState<WebSocketState>({
    isConnected: false,
    isConnecting: false,
    lastMessage: null,
    connectionAttempts: 0,
  });

  // Connect to WebSocket when user is authenticated
  useEffect(() => {
    if (isAuthenticated && token) {
      console.log('User authenticated, connecting to WebSocket...');
      connectWebSocket(token);
    } else {
      console.log('User not authenticated, disconnecting WebSocket...');
      disconnectWebSocket();
    }

    // Cleanup on unmount
    return () => {
      disconnectWebSocket();
    };
  }, [isAuthenticated, token]);

  const connectWebSocket = async (authToken: string) => {
    if (wsState.isConnecting || wsState.isConnected) {
      console.log('WebSocket already connecting or connected');
      return;
    }

    setWsState(prev => ({ 
      ...prev, 
      isConnecting: true,
      connectionAttempts: prev.connectionAttempts + 1
    }));

    try {
      const success = await webSocketService.connect(authToken);
      
      if (success) {
        console.log('WebSocket connected successfully');
      } else {
        console.error('Failed to connect to WebSocket');
        setWsState(prev => ({ 
          ...prev, 
          isConnecting: false 
        }));
      }
    } catch (error) {
      console.error('Error connecting to WebSocket:', error);
      setWsState(prev => ({ 
        ...prev, 
        isConnecting: false 
      }));
    }
  };

  const disconnectWebSocket = () => {
    webSocketService.disconnect();
    setWsState(prev => ({
      ...prev,
      isConnected: false,
      isConnecting: false,
      lastMessage: null,
    }));
  };

  // Set up WebSocket event handlers
  useEffect(() => {
    // Message handler
    const handleMessage = (message: WebSocketResponse) => {
      console.log('WebSocket message received:', message);
      setWsState(prev => ({
        ...prev,
        lastMessage: message,
      }));
    };

    // Connection handler
    const handleConnection = (connected: boolean) => {
      console.log('WebSocket connection status changed:', connected);
      setWsState(prev => ({
        ...prev,
        isConnected: connected,
        isConnecting: false,
      }));
    };

    // Error handler
    const handleError = (error: Event) => {
      console.error('WebSocket error:', error);
      setWsState(prev => ({
        ...prev,
        isConnecting: false,
      }));
    };

    // Add event listeners
    webSocketService.onMessage(handleMessage);
    webSocketService.onConnection(handleConnection);
    webSocketService.onError(handleError);

    // Cleanup event listeners
    return () => {
      webSocketService.offMessage(handleMessage);
      webSocketService.offConnection(handleConnection);
      webSocketService.offError(handleError);
    };
  }, []);

  // WebSocket methods
  const sendMessage = (message: Omit<import('../services/WebSocketService').WebSocketMessage, 'token'>) => {
    webSocketService.send({ ...message, token: token });
  };

  const ping = () => {
    webSocketService.send({ action: 'ping', token: token });
  };

  const echo = (message: string) => {
    webSocketService.send({ action: 'echo', message, token: token });
  };

  const broadcast = (message: string) => {
    webSocketService.send({ action: 'broadcast', message, token: token });
  };

  const getStatus = () => {
    webSocketService.send({ action: 'status', token: token });
  };

  // Provide the WebSocket context value to children components
  return (
    <WebSocketContext.Provider
      value={{
        ...wsState,
        sendMessage,
        ping,
        echo,
        broadcast,
        getStatus,
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
};

export default WebSocketContext;
