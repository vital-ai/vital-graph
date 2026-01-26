"""
PostgreSQL-based signal implementation for FUSEKI_POSTGRESQL backend.
Uses PostgreSQL NOTIFY/LISTEN for real-time notifications.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, Callable, List
import asyncpg

from ..backend_config import SignalManagerInterface
from ...utils.resource_manager import track_connection


logger = logging.getLogger(__name__)


class PostgreSQLSignalManager(SignalManagerInterface):
    """
    PostgreSQL-based signal implementation for FUSEKI_POSTGRESQL backend.
    Uses PostgreSQL NOTIFY/LISTEN for real-time notifications.
    
    This provides a significant enhancement over the Fuseki no-op signal manager
    by using PostgreSQL's built-in NOTIFY/LISTEN functionality for real-time events.
    """
    
    def __init__(self, postgresql_config: dict):
        """
        Initialize PostgreSQL signal manager.
        
        Args:
            postgresql_config: PostgreSQL configuration dictionary
        """
        self.config = postgresql_config
        self.connection = None
        self.listeners = {}
        self.callbacks = []
        self.space_callbacks = {}
        self.closed = False
        self.listen_task = None
        self._connection_lock = asyncio.Lock()  # Prevent concurrent operations on signal connection
        
    def _is_connection_closed(self, connection) -> bool:
        """
        Check if a connection is closed, handling different connection types.
        
        Args:
            connection: Database connection object
            
        Returns:
            bool: True if connection is closed or None, False if open
        """
        if connection is None:
            return True
            
        # Handle different connection types
        try:
            # asyncpg connections have is_closed() method
            if hasattr(connection, 'is_closed'):
                return connection.is_closed()
            # Some connection types might have .closed attribute
            elif hasattr(connection, 'closed'):
                return connection.closed
            # Some connection types might have _closed attribute
            elif hasattr(connection, '_closed'):
                return connection._closed
            else:
                # If we can't determine, assume it's open
                return False
        except Exception:
            # If any error occurs checking status, assume closed
            return True
        
        logger.info("PostgreSQLSignalManager initialized")
    
    async def connect(self) -> bool:
        """Establish dedicated PostgreSQL connection for NOTIFY/LISTEN operations."""
        try:
            logger.info("Connecting to PostgreSQL for signal operations...")
            
            # Use a dedicated connection for signal operations to avoid transaction conflicts
            self.connection = await asyncpg.connect(
                host=self.config.get('host', 'localhost'),
                port=self.config.get('port', 5432),
                database=self.config.get('database', 'vitalgraph'),
                user=self.config.get('username', 'vitalgraph_user'),
                password=self.config.get('password', 'vitalgraph_pass'),
                command_timeout=60
            )
            
            # Track the connection for proper cleanup
            track_connection(self.connection)
            
            # Verify this is a proper asyncpg connection
            if not isinstance(self.connection, asyncpg.Connection):
                logger.error(f"Invalid connection type {type(self.connection)} - expected asyncpg.Connection")
                logger.error("This indicates a connection setup issue")
                await self.connection.close()
                return False
            
            # Note: LISTEN channels will be set up in _listen_loop using add_listener API
            logger.debug("PostgreSQL connection established for notifications")
            
            # Start listening task
            self.listen_task = asyncio.create_task(self._listen_loop())
            
            logger.info("PostgreSQL signal manager connected successfully with notification support")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect PostgreSQL signal manager: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Close PostgreSQL signal connection."""
        try:
            self.closed = True
            
            # Cancel listening task
            if self.listen_task:
                self.listen_task.cancel()
                try:
                    await self.listen_task
                except asyncio.CancelledError:
                    pass
                self.listen_task = None
            
            # Close connection with proper cleanup
            if self.connection:
                try:
                    # Ensure connection is properly closed
                    if not self.connection.is_closed():
                        await self.connection.close()
                except Exception as e:
                    logger.debug(f"Connection close error (non-critical): {e}")
                finally:
                    self.connection = None
            
            # Clear callbacks and listeners
            self.callbacks.clear()
            self.space_callbacks.clear()
            self.listeners.clear()
            
            logger.info("PostgreSQL signal manager disconnected")
            return True
            
        except Exception as e:
            logger.error(f"Error disconnecting PostgreSQL signal manager: {e}")
            return False
    
    async def notify_space_created(self, space_id: str) -> None:
        """Notify that a space was created."""
        if self.closed:
            return
        
        await self._emit_signal('space_created', {
            'space_id': space_id,
            'event_type': 'created',
            'timestamp': asyncio.get_event_loop().time()
        })
        
        logger.info(f"🔔 Space created notification sent: {space_id}")
    
    async def notify_space_deleted(self, space_id: str) -> None:
        """Notify that a space was deleted."""
        if self.closed:
            return
        
        await self._emit_signal('space_deleted', {
            'space_id': space_id,
            'event_type': 'deleted',
            'timestamp': asyncio.get_event_loop().time()
        })
        
        logger.info(f"🔔 Space deleted notification sent: {space_id}")
    
    async def notify_space_updated(self, space_id: str) -> None:
        """Notify that a space was updated."""
        if self.closed:
            return
        
        await self._emit_signal('space_updated', {
            'space_id': space_id,
            'event_type': 'updated',
            'timestamp': asyncio.get_event_loop().time()
        })
        
        logger.info(f"🔔 Space updated notification sent: {space_id}")
    
    async def notify_graph_created(self, space_id: str, graph_id: str) -> None:
        """Notify that a graph was created."""
        if self.closed:
            return
        
        await self._emit_signal('graph_created', {
            'space_id': space_id,
            'graph_id': graph_id,
            'event_type': 'created',
            'timestamp': asyncio.get_event_loop().time()
        })
        
        logger.info(f"🔔 Graph created notification sent: {space_id}/{graph_id}")
    
    async def notify_graph_updated(self, space_id: str, graph_id: str) -> None:
        """Notify that a graph was updated."""
        if self.closed:
            return
        
        await self._emit_signal('graph_updated', {
            'space_id': space_id,
            'graph_id': graph_id,
            'event_type': 'updated',
            'timestamp': asyncio.get_event_loop().time()
        })
        
        logger.info(f"🔔 Graph updated notification sent: {space_id}/{graph_id}")
    
    async def notify_graph_deleted(self, space_id: str, graph_id: str) -> None:
        """Notify that a graph was deleted."""
        if self.closed:
            return
        
        await self._emit_signal('graph_deleted', {
            'space_id': space_id,
            'graph_id': graph_id,
            'event_type': 'deleted',
            'timestamp': asyncio.get_event_loop().time()
        })
        
        logger.info(f"🔔 Graph deleted notification sent: {space_id}/{graph_id}")
    
    async def notify_graphs_changed(self, signal_type: str) -> None:
        """Notify that graphs have changed (generic notification)."""
        if self.closed:
            return
        
        await self._emit_signal('graphs_changed', {
            'signal_type': signal_type,
            'event_type': 'graphs_changed',
            'timestamp': asyncio.get_event_loop().time()
        })
        
        logger.info(f"🔔 Graphs changed notification sent: {signal_type}")
    
    async def notify_graph_changed(self, graph_uri: str, signal_type: str) -> None:
        """Notify that a specific graph has changed."""
        if self.closed:
            return
        
        await self._emit_signal('graph_changed', {
            'graph_uri': graph_uri,
            'signal_type': signal_type,
            'event_type': 'graph_changed',
            'timestamp': asyncio.get_event_loop().time()
        })
        
        logger.info(f"🔔 Graph changed notification sent: {graph_uri} ({signal_type})")
    
    async def register_callback(self, callback: Callable) -> None:
        """Register a global callback for all notifications."""
        if callback not in self.callbacks:
            self.callbacks.append(callback)
            logger.debug(f"Registered global callback: {callback}")
    
    async def register_space_callback(self, space_id: str, callback: Callable) -> None:
        """Register a callback for notifications from a specific space."""
        if space_id not in self.space_callbacks:
            self.space_callbacks[space_id] = []
        
        if callback not in self.space_callbacks[space_id]:
            self.space_callbacks[space_id].append(callback)
            logger.debug(f"Registered space callback for {space_id}: {callback}")
    
    async def unregister_callback(self, callback: Callable) -> None:
        """Unregister a global callback."""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
            logger.debug(f"Unregistered global callback: {callback}")
    
    async def unregister_space_callback(self, space_id: str, callback: Callable) -> None:
        """Unregister a callback for a specific space."""
        if space_id in self.space_callbacks and callback in self.space_callbacks[space_id]:
            self.space_callbacks[space_id].remove(callback)
            logger.debug(f"Unregistered space callback for {space_id}: {callback}")
    
    # Internal methods
    
    async def _emit_signal(self, signal_type: str, data: dict) -> bool:
        """Emit signal using PostgreSQL NOTIFY with proper synchronization."""
        if not self.connection or self.closed:
            return False
        
        # Check if connection is still open
        if self._is_connection_closed(self.connection):
            logger.debug(f"Cannot emit signal {signal_type}: connection is closed")
            return False
        
        # Use lock to prevent concurrent operations on the signal connection
        async with self._connection_lock:
            try:
                payload = json.dumps(data)
                # NOTIFY command doesn't support parameterized queries, so we need to escape the payload
                escaped_payload = payload.replace("'", "''")  # Escape single quotes
                await self.connection.execute(f"NOTIFY {signal_type}, '{escaped_payload}'")
                return True
                
            except Exception as e:
                logger.error(f"Error emitting signal {signal_type}: {e}")
                return False
    
    async def _listen_for_signals(self, signal_type: str, callback) -> bool:
        """Listen for signals using PostgreSQL LISTEN."""
        if not self.connection or self.closed:
            return False
        
        try:
            await self.connection.execute(f"LISTEN {signal_type}")
            self.listeners[signal_type] = callback
            logger.debug(f"Started listening for signal: {signal_type}")
            return True
            
        except Exception as e:
            logger.error(f"Error listening for signal {signal_type}: {e}")
            return False
    
    async def _listen_loop(self):
        """Main listening loop for PostgreSQL notifications."""
        try:
            # Set up listeners for each channel using asyncpg's add_listener API
            def notification_handler(connection, pid, channel, payload):
                # Create a notification-like object for compatibility
                notification = type('Notification', (), {
                    'channel': channel,
                    'payload': payload,
                    'pid': pid
                })()
                # Schedule the handler to run in the event loop
                asyncio.create_task(self._handle_notification(notification))
            
            # Add listeners for default channels
            await self.connection.add_listener('space_created', notification_handler)
            await self.connection.add_listener('space_updated', notification_handler)
            await self.connection.add_listener('space_deleted', notification_handler)
            
            logger.info("PostgreSQL notification listeners set up successfully")
            
            # Keep the connection alive and listening
            while not self.closed and self.connection:
                await asyncio.sleep(1.0)
                    
        except asyncio.CancelledError:
            logger.debug("Listen loop cancelled")
        except Exception as e:
            logger.error(f"Listen loop error: {e}")
        finally:
            # Clean up listeners
            if self.connection and not self.connection.is_closed():
                try:
                    await self.connection.remove_listener('space_created', notification_handler)
                    await self.connection.remove_listener('space_updated', notification_handler)
                    await self.connection.remove_listener('space_deleted', notification_handler)
                except Exception as e:
                    logger.warning(f"Error removing listeners: {e}")
    
    async def _handle_notification(self, notification):
        """Handle incoming PostgreSQL notification."""
        try:
            signal_type = notification.channel
            payload = json.loads(notification.payload) if notification.payload else {}
            
            logger.debug(f"Received signal: {signal_type} with payload: {payload}")
            
            # Execute registered callbacks
            await self._execute_callbacks(signal_type, payload)
            
        except Exception as e:
            logger.error(f"Error handling notification: {e}")
    
    async def _execute_callbacks(self, signal_type: str, payload: dict):
        """Execute callbacks for a signal."""
        try:
            # Execute global callbacks
            for callback in self.callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(signal_type, payload)
                    else:
                        callback(signal_type, payload)
                except Exception as e:
                    logger.error(f"Error in global callback: {e}")
            
            # Execute space-specific callbacks
            space_id = payload.get('space_id')
            if space_id and space_id in self.space_callbacks:
                for callback in self.space_callbacks[space_id]:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(signal_type, payload)
                        else:
                            callback(signal_type, payload)
                    except Exception as e:
                        logger.error(f"Error in space callback: {e}")
                        
        except Exception as e:
            logger.error(f"Error executing callbacks: {e}")
    
    # Required abstract methods from SignalManagerInterface
    
    async def close(self) -> bool:
        """Close signal manager and cleanup resources."""
        try:
            logger.info("Closing PostgreSQL signal manager...")
            
            self.closed = True
            
            # Cancel listen task
            if self.listen_task and not self.listen_task.done():
                self.listen_task.cancel()
                try:
                    await self.listen_task
                except asyncio.CancelledError:
                    pass
            
            # Close connection
            if self.connection and not self.connection.is_closed():
                await self.connection.close()
            
            # Clear callbacks
            self.callbacks.clear()
            self.space_callbacks.clear()
            self.listeners.clear()
            
            logger.info("PostgreSQL signal manager closed")
            return True
            
        except Exception as e:
            logger.error(f"Error closing signal manager: {e}")
            return False
    
    async def subscribe_to_space_events(self, space_id: str, callback: Callable) -> bool:
        """Subscribe to events for a specific space."""
        try:
            if space_id not in self.space_callbacks:
                self.space_callbacks[space_id] = []
            
            self.space_callbacks[space_id].append(callback)
            
            # Listen to space-specific channel
            channel = f"space_{space_id}_events"
            if self.connection and not self.connection.is_closed():
                await self.connection.add_listener(channel, self._handle_notification)
                self.listeners[channel] = True
            
            logger.info(f"Subscribed to events for space: {space_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error subscribing to space events for {space_id}: {e}")
            return False
    
    async def unsubscribe_from_space_events(self, space_id: str, callback: Optional[Callable] = None) -> bool:
        """Unsubscribe from events for a specific space."""
        try:
            if space_id in self.space_callbacks:
                if callback:
                    # Remove specific callback
                    if callback in self.space_callbacks[space_id]:
                        self.space_callbacks[space_id].remove(callback)
                else:
                    # Remove all callbacks for this space
                    self.space_callbacks[space_id].clear()
                
                # If no more callbacks for this space, remove listener
                if not self.space_callbacks[space_id]:
                    del self.space_callbacks[space_id]
                    
                    channel = f"space_{space_id}_events"
                    if self.connection and not self.connection.is_closed() and channel in self.listeners:
                        await self.connection.remove_listener(channel, self._handle_notification)
                        del self.listeners[channel]
            
            logger.info(f"Unsubscribed from events for space: {space_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error unsubscribing from space events for {space_id}: {e}")
            return False
