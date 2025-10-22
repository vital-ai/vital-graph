"""
WebSocket handler for VitalGraph with token-based authentication.

This module provides WebSocket functionality that uses the same authentication
tokens as the REST API endpoints. Messages are sent as JSON with the token
included for validation.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect, HTTPException, status
from vitalgraph.auth.vitalgraph_auth import VitalGraphAuth

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections with authentication."""
    
    def __init__(self, auth_handler: VitalGraphAuth):
        # Store active connections by user
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.auth = auth_handler
    
    async def connect(self, websocket: WebSocket, token: str) -> Optional[str]:
        """
        Connect a WebSocket with JWT token authentication.
        
        Args:
            websocket: The WebSocket connection
            token: JWT authentication token from client
            
        Returns:
            Username if authentication successful, None otherwise
        """
        try:
            # Verify JWT token
            payload = self.auth.jwt_auth.verify_token(token, "access")
            username = payload.get("sub")
            
            if username not in self.auth.users_db:
                logger.warning(f"User not found: {username}")
                return None
            
            # Log connection details
            client_host = websocket.client.host
            client_port = websocket.client.port
            logger.info(f"WebSocket connection request from {client_host}:{client_port} for user '{username}'")
            
            # Note: websocket is already accepted in websocket_endpoint function
            logger.info(f"Processing WebSocket connection for user '{username}' from {client_host}:{client_port}")
            
            # Store connection by username
            if username not in self.active_connections:
                self.active_connections[username] = set()
            self.active_connections[username].add(websocket)
            
            # Log connection count
            connection_count = self.get_connection_count()
            connections_by_user = {user: len(conns) for user, conns in self.active_connections.items()}
            logger.info(f"Active WebSocket connections: {connection_count} total across {len(self.active_connections)} users")
            logger.debug(f"Connections by user: {connections_by_user}")
            
            logger.info(f"WebSocket connected for user: {username}")
            return username
            
        except HTTPException as e:
            logger.warning(f"JWT token validation failed: {e.detail}")
            return None
        except Exception as e:
            logger.error(f"Error during WebSocket connection: {e}")
            return None
    
    async def disconnect(self, websocket: WebSocket, username: Optional[str] = None) -> None:
        """Unregister a WebSocket connection."""
        client_host = websocket.client.host
        client_port = websocket.client.port
        
        if username and username in self.active_connections:
            logger.info(f"WebSocket disconnection for user '{username}' from {client_host}:{client_port}")
            
            # Remove the connection from the user's connections
            self.active_connections[username].discard(websocket)
            
            # Remove the user from active_connections if they have no connections left
            if not self.active_connections[username]:
                logger.info(f"User '{username}' has no more active connections, removing from active users")
                del self.active_connections[username]
        else:
            logger.warning(f"WebSocket disconnection from {client_host}:{client_port} for unknown user")
            
        # Log remaining connections
        connection_count = self.get_connection_count()
        logger.info(f"Remaining WebSocket connections: {connection_count} total across {len(self.active_connections)} users")
        logger.info(f"WebSocket disconnected for user: {username}")
    
    async def send_personal_message(self, message: str, username: str):
        """Send a message to all connections for a specific user."""
        if username in self.active_connections:
            disconnected = set()
            for websocket in self.active_connections[username]:
                try:
                    await websocket.send_text(message)
                except Exception as e:
                    logger.error(f"Error sending message to {username}: {e}")
                    disconnected.add(websocket)
            
            # Remove disconnected websockets
            for ws in disconnected:
                self.active_connections[username].discard(ws)
    
    async def broadcast(self, message: str):
        """Broadcast a message to all connected users."""
        for username, connections in self.active_connections.items():
            disconnected = set()
            for websocket in connections:
                try:
                    await websocket.send_text(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to {username}: {e}")
                    disconnected.add(websocket)
            
            # Remove disconnected websockets
            for ws in disconnected:
                connections.discard(ws)
    
    def get_connected_users(self) -> list:
        """Get list of currently connected usernames."""
        return list(self.active_connections.keys())
    
    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return sum(len(connections) for connections in self.active_connections.values())
    
    async def send_change_notification(self, group: str, user_id: str = None, space_id: str = None):
        """Send a change notification to all connected users."""
        change_message = {
            "type": "change",
            "group": group,
            "timestamp": json.dumps(datetime.now().isoformat())
        }
        
        if user_id:
            change_message["userId"] = user_id
        if space_id:
            change_message["spaceId"] = space_id
            
        await self.broadcast(json.dumps(change_message))
        logger.info(f"Sent change notification: group={group}, user_id={user_id}, space_id={space_id}")
    
    async def send_users_change(self):
        """Send notification that the users list has changed."""
        await self.send_change_notification("users")
    
    async def send_spaces_change(self):
        """Send notification that the spaces list has changed."""
        await self.send_change_notification("spaces")
    
    async def send_user_change(self, user_id: str):
        """Send notification that a specific user has changed."""
        await self.send_change_notification("user", user_id=user_id)
    
    async def send_space_change(self, space_id: str):
        """Send notification that a specific space has changed."""
        await self.send_change_notification(group="space", space_id=space_id)
        
    async def send_graphs_change(self):
        """Send notification that the graphs list has changed."""
        await self.send_change_notification(group="graphs")
        
    async def send_graph_change(self, graph_uri: str, space_id: str):
        """Send notification that a specific graph has changed."""
        await self.send_change_notification(group="graph", space_id=space_id, graph_uri=graph_uri)


class WebSocketHandler:
    """Handles WebSocket messages and routing."""
    
    def __init__(self, connection_manager: ConnectionManager):
        self.manager = connection_manager
    
    async def handle_message(self, websocket: WebSocket, username: str, message_data: dict):
        """
        Handle incoming WebSocket message.
        
        Args:
            websocket: The WebSocket connection
            username: Authenticated username
            message_data: Parsed JSON message data
        """
        try:
            message_type = message_data.get("type", "unknown")
            
            if message_type == "ping":
                # Respond to ping with pong
                await self.send_message(websocket, {
                    "type": "pong",
                    "timestamp": message_data.get("timestamp"),
                    "message": "Connection alive"
                })
            
            elif message_type == "echo":
                # Echo the message back
                await self.send_message(websocket, {
                    "type": "echo_response",
                    "original_message": message_data.get("message", ""),
                    "username": username
                })
            
            elif message_type == "broadcast":
                # Broadcast message to all connected users
                broadcast_data = {
                    "type": "broadcast_message",
                    "from_user": username,
                    "message": message_data.get("message", ""),
                    "timestamp": message_data.get("timestamp")
                }
                await self.manager.broadcast(json.dumps(broadcast_data))
            
            elif message_type == "get_status":
                # Send connection status
                await self.send_message(websocket, {
                    "type": "status_response",
                    "connected_users": self.manager.get_connected_users(),
                    "total_connections": self.manager.get_connection_count(),
                    "your_username": username
                })
            
            else:
                # Unknown message type
                await self.send_message(websocket, {
                    "type": "error",
                    "message": f"Unknown message type: {message_type}"
                })
                
        except Exception as e:
            logger.error(f"Error handling message from {username}: {e}")
            await self.send_message(websocket, {
                "type": "error",
                "message": "Internal server error"
            })
    
    async def send_message(self, websocket: WebSocket, data: dict):
        """Send a JSON message to a WebSocket."""
        try:
            # Check if websocket is still connected before sending
            if websocket.client_state.name != 'CONNECTED':
                return
            await websocket.send_text(json.dumps(data))
        except Exception as e:
            logger.debug(f"Error sending message (connection likely closed): {e}")


async def websocket_endpoint(websocket: WebSocket, connection_manager: ConnectionManager):
    """
    Main WebSocket endpoint handler.
    
    This function handles the WebSocket lifecycle:
    1. Waits for authentication message with token
    2. Validates token and establishes connection
    3. Handles incoming messages
    4. Cleans up on disconnect
    """
    username = None
    handler = WebSocketHandler(connection_manager)
    client_host = websocket.client.host
    client_port = websocket.client.port
    
    logger.info(f"New WebSocket endpoint connection from {client_host}:{client_port}")
    
    try:
        # Wait for authentication message
        logger.debug(f"Accepting initial WebSocket connection from {client_host}:{client_port}")
        await websocket.accept()
        
        # First message should contain authentication token
        logger.debug(f"Waiting for authentication message from {client_host}:{client_port}")
        auth_message = await websocket.receive_text()
        logger.debug(f"Received auth message from {client_host}:{client_port}: {auth_message[:50]}...")
        
        try:
            auth_data = json.loads(auth_message)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in authentication message from {client_host}:{client_port}: {e}")
            await websocket.send_text(json.dumps({
                "type": "auth_error",
                "message": "Invalid JSON format in authentication message"
            }))
            await websocket.close()
            return
        
        token = auth_data.get("token")
        if not token:
            logger.warning(f"Missing token in authentication message from {client_host}:{client_port}")
            await websocket.send_text(json.dumps({
                "type": "auth_error",
                "message": "Token required for authentication"
            }))
            await websocket.close()
            return
        
        # Authenticate using connection manager
        logger.info(f"Authenticating WebSocket connection from {client_host}:{client_port} with token: {token[:10]}...")
        username = await connection_manager.connect(websocket, token)
        if not username:
            logger.warning(f"Authentication failed for WebSocket from {client_host}:{client_port} with token: {token[:10]}...")
            await websocket.send_text(json.dumps({
                "type": "auth_error", 
                "message": "Invalid authentication token"
            }))
            await websocket.close()
            return
        
        logger.info(f"WebSocket authentication successful for user '{username}' from {client_host}:{client_port}")
        
        # Send authentication success
        await websocket.send_text(json.dumps({
            "type": "auth_success",
            "message": "WebSocket connection established",
            "username": username
        }))
        
        logger.info(f"Ready to receive messages from user '{username}' at {client_host}:{client_port}")
        while True:
            try:
                logger.debug(f"Waiting for message from user '{username}' at {client_host}:{client_port}")
                message = await websocket.receive_text()
                logger.debug(f"Received message from '{username}': {message[:50]}...")
                
                message_data = json.loads(message)
                message_type = message_data.get("type", "unknown")
                logger.info(f"Processing message type '{message_type}' from user '{username}'")
                
                # Validate JWT token in each message for security
                msg_token = message_data.get("token")
                if not msg_token:
                    await websocket.send_text(json.dumps({
                        "type": "auth_error",
                        "message": "Token required in message"
                    }))
                    break
                
                try:
                    payload = connection_manager.auth.jwt_auth.verify_token(msg_token, "access")
                    token_username = payload.get("sub")
                    
                    if token_username != username:
                        await websocket.send_text(json.dumps({
                            "type": "auth_error",
                            "message": "Token username mismatch"
                        }))
                        break
                        
                except HTTPException:
                    await websocket.send_text(json.dumps({
                        "type": "auth_error", 
                        "message": "Invalid or expired token"
                    }))
                    break
                
                logger.debug(f"Handling message type '{message_type}' for user '{username}'")
                await handler.handle_message(websocket, username, message_data)
                logger.debug(f"Successfully processed message type '{message_type}' for user '{username}'")
            except WebSocketDisconnect:
                # Break out of the message loop on disconnect
                logger.info(f"WebSocket disconnected for user '{username}' during message processing")
                break
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in message from '{username}': {e}")
                try:
                    if websocket.client_state.name == 'CONNECTED':
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "Invalid JSON format in message"
                        }))
                except Exception:
                    pass  # Connection already closed
            except Exception as e:
                logger.error(f"Error processing message from '{username}': {e}")
                try:
                    if websocket.client_state.name == 'CONNECTED':
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "Error processing message"
                        }))
                except Exception:
                    pass  # Connection already closed
            
    except WebSocketDisconnect as e:
        logger.info(f"WebSocket disconnected for user: {username or 'unknown'} from {client_host}:{client_port} - code: {e.code}")
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON received from {client_host}:{client_port}: {e}")
        try:
            if websocket.client_state.name == 'CONNECTED':
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format"
                }))
        except Exception:
            pass  # Connection already closed
    except Exception as e:
        logger.error(f"WebSocket error for {username or 'unknown'} from {client_host}:{client_port}: {str(e)}")
    finally:
        try:
            if username:
                await connection_manager.disconnect(websocket, username)
            else:
                logger.info(f"Cleaning up unauthenticated WebSocket connection from {client_host}:{client_port}")
        except Exception as e:
            logger.error(f"Error during WebSocket cleanup: {str(e)}")
        
        logger.info(f"WebSocket connection finalized for {username or 'unknown'} from {client_host}:{client_port}")
