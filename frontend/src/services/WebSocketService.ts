/**
 * WebSocket service for VitalGraph with JWT authentication and reconnection logic.
 * 
 * This service manages WebSocket connections to the VitalGraph backend,
 * handles JWT authentication using the same tokens as REST endpoints,
 * and provides automatic reconnection with exponential backoff.
 */

import { authService } from './AuthService';

export interface WebSocketMessage {
  type: string;
  token: string;
  [key: string]: any;
}

export interface WebSocketResponse {
  type: string;
  [key: string]: any;
}

export type MessageHandler = (message: WebSocketResponse) => void;
export type ConnectionHandler = (connected: boolean) => void;
export type ErrorHandler = (error: Event) => void;

export interface IWebSocketService {
  url: string;
  connect(token: string): Promise<boolean>;
  disconnect(): Promise<void>;
  send(data: any): void;
  onMessage(handler: MessageHandler): void;
  offMessage(handler: MessageHandler): void;
  onConnection(handler: ConnectionHandler): void;
  offConnection(handler: ConnectionHandler): void;
  onError(handler: ErrorHandler): void;
  offError(handler: ErrorHandler): void;
  setReconnectInterval(minutes: number): void;
}

export class WebSocketServiceImpl implements IWebSocketService {
  ws: WebSocket | null = null;
  private token: string | null = null;
  url: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000; // Start with 1 second
  private maxReconnectDelay = 30000; // Max 30 seconds
  private reconnectTimer: number | null = null;
  private isConnected = false;
  private shouldReconnect = true;
  private messageHandlers: MessageHandler[] = [];
  private connectionHandlers: ConnectionHandler[] = [];
  private errorHandlers: ErrorHandler[] = [];
  private periodicReconnectTimer: number | null = null;
  private reconnectIntervalMs = 5 * 60 * 1000; // Default: 5 minutes
  private _manualReconnectInProgress = false; // Flag to prevent automatic reconnect during manual reconnect

  constructor() {
    // Determine WebSocket URL based on current location
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    
    // In development, the backend runs on port 8001
    // In production, we can use the same host as the frontend
    let host;
    if (import.meta.env.DEV) {
      // Development - use localhost:8001 as backend
      host = window.location.hostname + ':8001';
    } else {
      // Production - use same host as frontend
      host = window.location.host;
    }
    
    this.url = `${protocol}//${host}/api/ws`;
    console.log('WebSocket URL configured as:', this.url);
  }

  /**
   * Set the interval for periodic disconnect/reconnect (in minutes)
   */
  setReconnectInterval(minutes: number): void {
    this.reconnectIntervalMs = minutes * 60 * 1000;
    console.log(`🔄 Periodic reconnect interval set to ${minutes} minutes`);
    
    // Reset the timer if already running
    this.clearPeriodicReconnectTimer();
    
    // Start new timer if connected
    if (this.isConnected) {
      this.startPeriodicReconnectTimer();
    }
  }
  
  /**
   * Start timer for periodic reconnection
   */
  private startPeriodicReconnectTimer(): void {
    this.clearPeriodicReconnectTimer();
    
    console.log(`🕒 Starting periodic reconnect timer: ${this.reconnectIntervalMs / 60000} minutes`);
    
    this.periodicReconnectTimer = setTimeout(async () => {
      if (this.isConnected) {
        console.log('🔄 Performing periodic WebSocket reconnect...');
        
        // Use disconnectForReconnect instead of disconnect to preserve reconnect flag
        await this.disconnectForReconnect();
        
        // Short delay before reconnecting
        setTimeout(() => {
          if (this.token) {
            console.log('🔄 Reconnecting WebSocket after periodic disconnect...');
            this.connect(this.token).catch(err => {
              console.error('❌ Error during periodic reconnect:', err);
            });
          } else {
            console.error('❌ Cannot reconnect: No authentication token available');
          }
        }, 1000);
      }
    }, this.reconnectIntervalMs);
  }
  
  /**
   * Clear the periodic reconnect timer
   */
  private clearPeriodicReconnectTimer(): void {
    if (this.periodicReconnectTimer) {
      clearTimeout(this.periodicReconnectTimer);
      this.periodicReconnectTimer = null;
    }
  }

  /**
   * Connect to WebSocket with JWT authentication token
   */
  async connect(token: string): Promise<boolean> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      console.log('🔗 WebSocket already connected');
      return true;
    }

    // Validate JWT token format (should have 3 parts separated by dots)
    if (!token || token.split('.').length !== 3) {
      console.error('❌ Invalid JWT token format for WebSocket connection');
      return false;
    }

    this.token = token;
    this.shouldReconnect = true;
    this._manualReconnectInProgress = false; // Reset manual reconnect flag when connecting

    return new Promise((resolve) => {
      try {
        console.log(`🔄 Attempting to connect to WebSocket: ${this.url}`);
        this.ws = new WebSocket(this.url);
        console.log(`🔌 Connecting to WebSocket at: ${this.url}`);
        // Detailed connection information
        console.log(`🔍 WebSocket details:
          - URL: ${this.url}
          - Protocol: ${window.location.protocol}
          - Host: ${window.location.host}
          - Origin: ${window.location.origin}
        `);
        
        this.ws.onopen = async () => {
          console.log('🔌 WebSocket connection opened to:', this.url);
          if (this.ws) {
            console.log('🔢 WebSocket ready state:', this.ws.readyState);
            console.log('📊 Connection details:', {
              protocol: this.ws.protocol || 'none',
              extensions: this.ws.extensions || 'none',
              bufferedAmount: this.ws.bufferedAmount
            });
          }
          
          // Wait for WebSocket to be fully ready before sending
          const sendAuthMessage = () => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
              const authMessage = {
                type: 'auth',
                token: this.token!
              };
              
              console.log('🔐 Sending authentication message...');
              this.ws.send(JSON.stringify(authMessage));
            } else {
              // Retry after a short delay if not ready
              setTimeout(sendAuthMessage, 10);
            }
          };
          
          sendAuthMessage();
          
          // Wait for auth response
          const authHandler = (event: MessageEvent) => {
            try {
              const data = JSON.parse(event.data);
              console.log('📥 Received WebSocket message:', data);
              
              if (data.type === 'auth_success') {
                console.log('🔓 WebSocket authentication successful');
                console.log('👤 Authenticated as:', data.username);
                this.isConnected = true;
                this.reconnectAttempts = 0;
                this.reconnectDelay = 1000; // Reset delay
                this.notifyConnectionHandlers(true);
                
                // Start the periodic reconnect timer
                this.startPeriodicReconnectTimer();
                
                resolve(true);
              } else if (data.type === 'auth_error') {
                console.error('🔒 WebSocket authentication failed:', data.message);
                console.error('🔍 Auth error details:', data);
                this.ws!.close();
                resolve(false);
              }
              
              // Remove this temporary handler
              this.ws!.removeEventListener('message', authHandler);
            } catch (error) {
              console.error('Error parsing auth response:', error);
              resolve(false);
            }
          };
          
          this.ws!.addEventListener('message', authHandler);
        };

        this.ws.onmessage = (event) => {
          try {
            const message: WebSocketResponse = JSON.parse(event.data);
            this.notifyMessageHandlers(message);
          } catch (error) {
            console.error('Error parsing WebSocket message:', error);
          }
        };

        this.ws.onclose = (event) => {
          console.log('🔌 WebSocket connection closed:', event.code, event.reason);
          this.isConnected = false;
          this.notifyConnectionHandlers(false);
          
          if (this.shouldReconnect && !this._manualReconnectInProgress) {
            console.log('🔄 Scheduling reconnection...');
            this.scheduleReconnect();
          } else if (this._manualReconnectInProgress) {
            console.log('🛑 Manual reconnect in progress, skipping automatic reconnect');
          } else {
            console.log('🛑 Reconnection disabled, staying disconnected');
          }
          
          if (!this.isConnected) {
            resolve(false);
          }
        };

        this.ws.onerror = (error) => {
          console.error('❌ WebSocket error:', error);
          console.error('❌ WebSocket error details:', {
            url: this.url,
            readyState: this.ws ? this.ws.readyState : 'undefined',
            protocol: window.location.protocol,
            host: window.location.host,
            origin: window.location.origin,
          });
          
          // Try to provide more helpful debug information
          if (this.url.includes('localhost')) {
            console.log('🔎 Troubleshooting tips:');
            console.log('  1. Confirm backend server is running on the correct port');
            console.log('  2. Check CORS settings in backend server');
            console.log('  3. Verify WebSocket endpoint is properly registered');
          }
          
          this.notifyErrorHandlers(error);
          
          // Even after error, we should still try to reconnect
          // unless shouldReconnect is explicitly set to false
          if (this.shouldReconnect) {
            console.log('🔄 Will attempt to reconnect after WebSocket error');
          }
          
          if (!this.isConnected) {
            resolve(false);
          }
        };

      } catch (error) {
        console.error('Error creating WebSocket connection:', error);
        resolve(false);
      }
    });
  }

  /**
   * Send data over the WebSocket connection with current JWT token
   */
  send(data: any): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('📤 Cannot send message: WebSocket not connected');
      return;
    }
    
    // Always include current JWT access token
    const currentToken = authService.getAccessToken();
    if (!currentToken) {
      console.error('❌ No valid access token available for WebSocket message');
      return;
    }
    
    const messageWithToken = {
      ...data,
      token: currentToken
    };
    
    try {
      this.ws.send(JSON.stringify(messageWithToken));
      console.log('📤 Sent WebSocket message:', { ...data, token: '[JWT_HIDDEN]' });
    } catch (error) {
      console.error('❌ Error sending WebSocket message:', error);
    }
  }
  /**
   * Disconnect WebSocket and stop reconnection attempts
   */
  async disconnect(): Promise<void> {
    console.log('🔌 Disconnecting WebSocket');
    this.shouldReconnect = false;
    
    // Clear reconnect timers
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    
    this.clearPeriodicReconnectTimer();
    
    if (!this.ws) {
      console.log('No active WebSocket connection to disconnect');
      return;
    }
    
    return new Promise<void>((resolve) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.onclose = () => {
          console.log('WebSocket disconnected by user');
          this.isConnected = false;
          this.notifyConnectionHandlers(false);
          resolve();
        };
        
        this.ws.close();
      } else {
        console.log('WebSocket already disconnected');
        this.isConnected = false;
        this.notifyConnectionHandlers(false);
        resolve();
      }
    });
  }

  /**
   * Disconnect WebSocket without stopping reconnection attempts
   * Used for periodic reconnection
   */
  async disconnectForReconnect(): Promise<void> {
    console.log('🔄 Temporarily disconnecting WebSocket for reconnect');
    // Set flag to prevent automatic reconnect during manual reconnect
    this._manualReconnectInProgress = true;
    
    if (!this.ws) {
      console.log('No active WebSocket connection to temporarily disconnect');
      this._manualReconnectInProgress = false; // Reset flag if no connection
      return;
    }
    
    // First disconnect
    await new Promise<void>((resolve) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        // Simply override onclose for this disconnect only
        this.ws.onclose = () => {
          console.log('WebSocket temporarily disconnected for reconnect');
          this.isConnected = false;
          this.notifyConnectionHandlers(false);
          resolve();
        };
        
        this.ws.close();
      } else {
        console.log('WebSocket already disconnected');
        this.isConnected = false;
        this.notifyConnectionHandlers(false);
        resolve();
      }
    });
    
    // After disconnecting, reconnect with a small delay
    await new Promise<void>(resolve => setTimeout(resolve, 1000));
    
    // Clear the manual reconnect flag before reconnecting
    this._manualReconnectInProgress = false;
    
    // Then reconnect if we have a token
    if (this.token) {
      console.log('🔄 Reconnecting after manual periodic disconnect...');
      try {
        await this.connect(this.token);
        console.log('✅ Manual reconnect successful');
      } catch (err) {
        console.error('❌ Error during manual reconnect:', err);
      }
    } else {
      console.error('❌ Cannot reconnect: No authentication token available');
    }
  }
  
  /**
   * Send a ping message to test connection
   */
  ping(): void {
    this.send({
      type: 'ping',
      token: this.token,
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Send an echo message
   */
  echo(message: string): void {
    this.send({
      type: 'echo',
      token: this.token,
      message: message
    });
  }

  /**
   * Broadcast a message to all connected users
   */
  broadcast(message: string): void {
    this.send({
      type: 'broadcast',
      token: this.token,
      message: message,
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Get connection status
   */
  getStatus(): void {
    this.send({
      type: 'get_status',
      token: this.token
    });
  }

  /**
   * Check if WebSocket is connected
   */
  get connected(): boolean {
    return this.isConnected;
  }

  /**
   * Add message handler
   */
  onMessage(handler: MessageHandler): void {
    this.messageHandlers.push(handler);
  }

  /**
   * Remove message handler
   */
  offMessage(handler: MessageHandler): void {
    const index = this.messageHandlers.indexOf(handler);
    if (index > -1) {
      this.messageHandlers.splice(index, 1);
    }
  }

  /**
   * Add connection status handler
   */
  onConnection(handler: ConnectionHandler): void {
    this.connectionHandlers.push(handler);
  }

  /**
   * Remove connection status handler
   */
  offConnection(handler: ConnectionHandler): void {
    const index = this.connectionHandlers.indexOf(handler);
    if (index > -1) {
      this.connectionHandlers.splice(index, 1);
    }
  }

  /**
   * Add error handler
   */
  onError(handler: ErrorHandler): void {
    this.errorHandlers.push(handler);
  }

  /**
   * Remove error handler
   */
  offError(handler: ErrorHandler): void {
    const index = this.errorHandlers.indexOf(handler);
    if (index > -1) {
      this.errorHandlers.splice(index, 1);
    }
  }

  /**
   * Schedule reconnection with exponential backoff
   */
  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached');
      return;
    }

    this.reconnectAttempts++;
    
    // Exponential backoff with jitter
    const delay = Math.min(
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
      this.maxReconnectDelay
    );
    
    const jitter = Math.random() * 1000; // Add up to 1 second of jitter
    const finalDelay = delay + jitter;

    console.log(`⏰ Scheduling reconnection attempt ${this.reconnectAttempts} in ${Math.round(finalDelay)}ms`);

    this.reconnectTimer = setTimeout(async () => {
      if (this.shouldReconnect && this.token && !this._manualReconnectInProgress) {
        console.log(`🔄 Reconnection attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts}`);
        const success = await this.connect(this.token);
        
        if (!success) {
          console.log('❌ Reconnection failed, will try again');
        } else {
          console.log('✅ Reconnection successful!');
        }
      } else if (this._manualReconnectInProgress) {
        console.log('🛑 Reconnection suppressed: manual reconnect in progress');
      } else {
        console.log('🛑 Reconnection cancelled (shouldReconnect=false or no token)');
      }
    }, finalDelay);
  }

  /**
   * Notify all message handlers
   */
  private notifyMessageHandlers(message: WebSocketResponse): void {
    this.messageHandlers.forEach(handler => {
      try {
        handler(message);
      } catch (error) {
        console.error('Error in message handler:', error);
      }
    });
  }

  /**
   * Notify all connection handlers
   */
  private notifyConnectionHandlers(connected: boolean): void {
    this.connectionHandlers.forEach(handler => {
      try {
        handler(connected);
      } catch (error) {
        console.error('Error in connection handler:', error);
      }
    });
  }

  /**
   * Notify all error handlers
   */
  private notifyErrorHandlers(error: Event): void {
    this.errorHandlers.forEach(handler => {
      try {
        handler(error);
      } catch (error) {
        console.error('Error in error handler:', error);
      }
    });
  }
}

// Create a singleton instance
export const webSocketService = new WebSocketServiceImpl();
export type WebSocketService = IWebSocketService;
