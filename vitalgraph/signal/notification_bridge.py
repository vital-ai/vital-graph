"""
Bridge between PostgreSQL notifications and WebSocket connections.

This module registers callbacks with the SignalManager to forward 
PostgreSQL notifications to WebSocket clients via the ConnectionManager.
"""

import asyncio
import logging
from typing import Optional

from vitalgraph.signal.signal_manager import (
    SignalManager,
    CHANNEL_USERS, CHANNEL_SPACES, CHANNEL_GRAPHS,
    CHANNEL_USER, CHANNEL_SPACE, CHANNEL_GRAPH
)
from vitalgraph.websocket.websocket_handler import ConnectionManager

logger = logging.getLogger(__name__)

class NotificationBridge:
    """Bridges PostgreSQL notifications to WebSocket connections."""
    
    def __init__(self, signal_manager: SignalManager, connection_manager: ConnectionManager):
        """
        Initialize the notification bridge.
        
        Args:
            signal_manager: SignalManager instance for PostgreSQL notifications
            connection_manager: ConnectionManager instance for WebSocket connections
        """
        self.signal_manager = signal_manager
        self.connection_manager = connection_manager
        self.registered = False
        
    async def register_callbacks(self):
        """Register callbacks from SignalManager to ConnectionManager."""
        if self.registered:
            logger.warning("Callbacks already registered")
            return
            
        if not self.signal_manager:
            logger.error("No SignalManager available")
            return
            
        if not self.connection_manager:
            logger.error("No ConnectionManager available")
            return
        
        # Register callback for users collection changes
        self.signal_manager.register_callback(
            CHANNEL_USERS, 
            self._handle_users_notification
        )
        
        # Register callback for spaces collection changes
        self.signal_manager.register_callback(
            CHANNEL_SPACES, 
            self._handle_spaces_notification
        )
        
        # Register callback for graphs collection changes
        self.signal_manager.register_callback(
            CHANNEL_GRAPHS, 
            self._handle_graphs_notification
        )
        
        # Register callback for individual user changes
        self.signal_manager.register_callback(
            CHANNEL_USER, 
            self._handle_user_notification
        )
        
        # Register callback for individual space changes
        self.signal_manager.register_callback(
            CHANNEL_SPACE, 
            self._handle_space_notification
        )
        
        # Register callback for individual graph changes
        self.signal_manager.register_callback(
            CHANNEL_GRAPH, 
            self._handle_graph_notification
        )
        
        self.registered = True
        logger.info("Notification callbacks registered successfully")
    
    async def _handle_users_notification(self, data: dict):
        """Handle notification for users collection changes."""
        try:
            signal_type = data.get('type', 'unknown')
            logger.debug(f"Received users notification: {signal_type}")
            await self.connection_manager.send_users_change()
        except Exception as e:
            logger.error(f"Error handling users notification: {e}")
    
    async def _handle_spaces_notification(self, data: dict):
        """Handle notification for spaces collection changes."""
        try:
            signal_type = data.get('type', 'unknown')
            logger.debug(f"Received spaces notification: {signal_type}")
            await self.connection_manager.send_spaces_change()
        except Exception as e:
            logger.error(f"Error handling spaces notification: {e}")
    
    async def _handle_graphs_notification(self, data: dict):
        """Handle notification for graphs collection changes."""
        try:
            signal_type = data.get('type', 'unknown')
            logger.debug(f"Received graphs notification: {signal_type}")
            await self.connection_manager.send_graphs_change()
        except Exception as e:
            logger.error(f"Error handling graphs notification: {e}")
    
    async def _handle_user_notification(self, data: dict):
        """Handle notification for individual user changes."""
        try:
            user_id = data.get('user_id')
            signal_type = data.get('type', 'unknown')
            
            if not user_id:
                logger.warning(f"Received user notification without user_id: {data}")
                return
                
            logger.debug(f"Received user notification: {signal_type} for user {user_id}")
            await self.connection_manager.send_user_change(user_id)
        except Exception as e:
            logger.error(f"Error handling user notification: {e}")
    
    async def _handle_space_notification(self, data: dict):
        """Handle notification for individual space changes."""
        try:
            space_id = data.get('space_id')
            signal_type = data.get('type', 'unknown')
            
            if not space_id:
                logger.warning(f"Received space notification without space_id: {data}")
                return
                
            logger.debug(f"Received space notification: {signal_type} for space {space_id}")
            await self.connection_manager.send_space_change(space_id)
        except Exception as e:
            logger.error(f"Error handling space notification: {e}")
    
    async def _handle_graph_notification(self, data: dict):
        """Handle notification for individual graph changes."""
        try:
            graph_uri = data.get('graph_uri')
            space_id = data.get('space_id')
            signal_type = data.get('type', 'unknown')
            
            if not graph_uri or not space_id:
                logger.warning(f"Received graph notification without required data: {data}")
                return
                
            logger.debug(f"Received graph notification: {signal_type} for graph {graph_uri} in space {space_id}")
            await self.connection_manager.send_graph_change(graph_uri, space_id)
        except Exception as e:
            logger.error(f"Error handling graph notification: {e}")


async def setup_notification_bridge(signal_manager: SignalManager, connection_manager: ConnectionManager) -> Optional[NotificationBridge]:
    """
    Set up the notification bridge between PostgreSQL and WebSocket.
    
    Args:
        signal_manager: SignalManager instance
        connection_manager: ConnectionManager instance
        
    Returns:
        NotificationBridge instance if successful, None otherwise
    """
    if not signal_manager:
        logger.error("Cannot set up notification bridge: No SignalManager provided")
        return None
        
    if not connection_manager:
        logger.error("Cannot set up notification bridge: No ConnectionManager provided")
        return None
    
    try:
        bridge = NotificationBridge(signal_manager, connection_manager)
        await bridge.register_callbacks()
        logger.info("Notification bridge successfully set up")
        return bridge
    except Exception as e:
        logger.error(f"Error setting up notification bridge: {e}")
        return None
