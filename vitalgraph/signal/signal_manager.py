
import asyncio
import json
import logging
import asyncpg
from asyncio import Task
from typing import Dict, List, Optional, Callable, Set, Awaitable

logger = logging.getLogger(__name__)

# Constants for notification channels
CHANNEL_USERS = "vitalgraph_users"
CHANNEL_SPACES = "vitalgraph_spaces"
CHANNEL_GRAPHS = "vitalgraph_graphs"
CHANNEL_USER = "vitalgraph_user"
CHANNEL_SPACE = "vitalgraph_space" 
CHANNEL_GRAPH = "vitalgraph_graph"
CHANNEL_ENTITY_DEDUP = "vitalgraph_entity_dedup"
CHANNEL_PROCESS = "vitalgraph_process"
CHANNEL_CACHE_INVALIDATE = "vitalgraph_cache_invalidate"

# Signal types
SIGNAL_TYPE_CREATED = "created"
SIGNAL_TYPE_UPDATED = "updated"
SIGNAL_TYPE_DELETED = "deleted"

class SignalManager:
    """
    SignalManager handles PostgreSQL NOTIFY/LISTEN for inter-process communication.
    
    This class manages both sending and receiving notifications via PostgreSQL's
    built-in notification system, allowing different instances of VitalGraph to
    communicate database changes.
    """
    
    def __init__(self, db_impl):
        """
        Initialize the SignalManager.
        
        Args:
            db_impl: PostgreSQLDbImpl instance to obtain database connections
        """
        self.db_impl = db_impl
        self.logger = logger
        self.listen_connection = None  # Persistent connection for LISTEN
        self.notify_connection = None  # Persistent connection for NOTIFY
        self.notify_lock = asyncio.Lock()  # Lock for notify connection
        self.listener_task: Optional[Task] = None
        self.running = False
        
        # Callbacks for notification channels
        self.callbacks: Dict[str, List[Callable[[dict], Awaitable[None]]]] = {
            CHANNEL_USERS: [],
            CHANNEL_SPACES: [],
            CHANNEL_GRAPHS: [],
            CHANNEL_USER: [],
            CHANNEL_SPACE: [],
            CHANNEL_GRAPH: [],
            CHANNEL_ENTITY_DEDUP: [],
            CHANNEL_PROCESS: [],
            CHANNEL_CACHE_INVALIDATE: [],
        }
        
        # Set of channels we're currently listening to
        self.active_channels: Set[str] = set()
        
        # Register default logging callbacks for all channels
        self._register_default_logging_callbacks()
    
    def _is_connection_closed(self, connection) -> bool:
        """
        Check if an asyncpg connection is closed.
        
        Args:
            connection: asyncpg connection object
            
        Returns:
            bool: True if connection is closed or None, False if open
        """
        if connection is None:
            return True
        try:
            return connection.is_closed()
        except Exception:
            return True
    
    def _register_default_logging_callbacks(self):
        """Register default logging callbacks for all notification channels."""
        # Users notifications
        self.register_callback(CHANNEL_USERS, self._log_users_notification)
        self.register_callback(CHANNEL_USER, self._log_user_notification)
        
        # Spaces notifications
        self.register_callback(CHANNEL_SPACES, self._log_spaces_notification)
        self.register_callback(CHANNEL_SPACE, self._log_space_notification)
        
        # Graphs notifications
        self.register_callback(CHANNEL_GRAPHS, self._log_graphs_notification)
        self.register_callback(CHANNEL_GRAPH, self._log_graph_notification)
        
        self.logger.info("🔔 Registered default logging callbacks for all notification channels")
    
    def _log_users_notification(self, data: dict):
        """Log users list change notifications."""
        signal_type = data.get('type', 'unknown')
        timestamp = data.get('timestamp', 'unknown')
        self.logger.info(f"📢 USERS NOTIFICATION: {signal_type.upper()} at {timestamp}")
        
    def _log_user_notification(self, data: dict):
        """Log specific user change notifications."""
        signal_type = data.get('type', 'unknown')
        user_id = data.get('user_id', 'unknown')
        timestamp = data.get('timestamp', 'unknown')
        self.logger.info(f"👤 USER NOTIFICATION: User '{user_id}' {signal_type.upper()} at {timestamp}")
        
    def _log_spaces_notification(self, data: dict):
        """Log spaces list change notifications."""
        signal_type = data.get('type', 'unknown')
        timestamp = data.get('timestamp', 'unknown')
        self.logger.info(f"📢 SPACES NOTIFICATION: {signal_type.upper()} at {timestamp}")
        
    def _log_space_notification(self, data: dict):
        """Log specific space change notifications."""
        signal_type = data.get('type', 'unknown')
        space_id = data.get('space_id', 'unknown')
        timestamp = data.get('timestamp', 'unknown')
        self.logger.info(f"🏠 SPACE NOTIFICATION: Space '{space_id}' {signal_type.upper()} at {timestamp}")
        
    def _log_graphs_notification(self, data: dict):
        """Log graphs list change notifications."""
        signal_type = data.get('type', 'unknown')
        timestamp = data.get('timestamp', 'unknown')
        self.logger.info(f"📢 GRAPHS NOTIFICATION: {signal_type.upper()} at {timestamp}")
        
    def _log_graph_notification(self, data: dict):
        """Log specific graph change notifications."""
        signal_type = data.get('type', 'unknown')
        graph_uri = data.get('graph_uri', 'unknown')
        timestamp = data.get('timestamp', 'unknown')
        self.logger.info(f"📊 GRAPH NOTIFICATION: Graph '{graph_uri}' {signal_type.upper()} at {timestamp}")
    
    async def start_listening(self):
        """Start the notification listener in a background task."""
        if self.listener_task is not None:
            self.logger.warning("Listener task already running")
            return
            
        self.running = True
        self.listener_task = asyncio.create_task(self._listen_for_notifications())
        self.logger.info("PostgreSQL notification listener started")
    
    async def stop_listening(self):
        """Stop the notification listener and clean up resources."""
        self.running = False
        
        # Cancel listener task
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
            self.listener_task = None
            
        # Close listen connection
        if self.listen_connection and not self._is_connection_closed(self.listen_connection):
            try:
                await self.listen_connection.close()
            except Exception as e:
                self.logger.debug(f"Error closing listen connection: {e}")
            self.listen_connection = None
            
        # Close notify connection
        await self._close_notify_connection()
            
        self.logger.info("PostgreSQL notification listener stopped")
    
    def _get_db_config(self) -> dict:
        """Extract database config dict from db_impl."""
        if hasattr(self.db_impl, 'config'):
            if hasattr(self.db_impl.config, 'get_database_config'):
                return self.db_impl.config.get_database_config()
            else:
                return self.db_impl.config
        raise AttributeError(f"Backend {type(self.db_impl)} has no config for building connection")

    async def _create_dedicated_connection(self) -> asyncpg.Connection:
        """Create a dedicated asyncpg connection (not from the pool) for signal operations."""
        db_config = self._get_db_config()
        return await asyncpg.connect(
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', 5432),
            database=db_config.get('database', 'vitalgraph'),
            user=db_config.get('username', 'vitalgraph_user'),
            password=db_config.get('password', 'vitalgraph_pass'),
            command_timeout=60,
        )

    async def _listen_for_notifications(self):
        """Background task that listens for PostgreSQL notifications using asyncpg."""
        retry_delay = 1
        max_retry_delay = 30
        
        while self.running:
            self.listen_connection = None
            try:
                self.listen_connection = await self._create_dedicated_connection()
                retry_delay = 1  # Reset on successful connect
                
                # Define the notification handler that asyncpg will call
                def notification_handler(connection, pid, channel, payload):
                    asyncio.create_task(
                        self._process_notification_async(connection, pid, channel, payload)
                    )
                
                # Register listener for each channel using asyncpg add_listener
                for channel in self.callbacks.keys():
                    try:
                        await self.listen_connection.add_listener(channel, notification_handler)
                        self.logger.debug(f"🔔 Added asyncpg listener for channel: {channel}")
                    except Exception as e:
                        self.logger.error(f"Error adding listener for {channel}: {e}")
                    
                self.active_channels = set(self.callbacks.keys())
                self.logger.info(
                    f"PostgreSQL notification listener connected, "
                    f"listening on {len(self.active_channels)} channels"
                )
                
                # Keep connection alive — asyncpg delivers notifications via the handler
                while self.running:
                    await asyncio.sleep(1.0)
                    
            except asyncio.CancelledError:
                self.logger.debug("Listen task cancelled")
                return
            except Exception as e:
                self.logger.error(f"Error in notification listener: {e}")
                self.active_channels.clear()
            finally:
                if self.listen_connection and not self._is_connection_closed(self.listen_connection):
                    try:
                        await self.listen_connection.close()
                    except Exception as e:
                        self.logger.debug(f"Error closing listen connection: {e}")
                    self.listen_connection = None
                        
            # Retry if still supposed to be running
            if self.running:
                self.logger.info(f"Reconnecting in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
    
    def _process_notification(self, conn, pid, channel, payload):
        """
        Process a notification received from PostgreSQL.
        
        Args:
            conn: Database connection
            pid: Process ID that sent the notification
            channel: Notification channel
            payload: Notification payload
        """
        self.logger.debug(f"🔔 _process_notification called: channel={channel}, payload={payload}")
        try:
            # Parse JSON payload if it's a string
            if isinstance(payload, str):
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = payload
            else:
                data = payload
                
            self.logger.info(f" Scheduling callbacks for channel '{channel}' with {len(self.callbacks.get(channel, []))} callbacks")
            # Schedule callback execution
            asyncio.create_task(self._execute_callbacks(channel, data))
            
        except Exception as e:
            self.logger.error(f"Error processing notification on channel '{channel}': {str(e)}")
    
    async def _execute_callbacks(self, channel: str, data: dict):
        """
        Execute all callbacks registered for a channel.
        
        Args:
            channel: Notification channel
            data: Notification data
        """
        self.logger.debug(f"🔔 _execute_callbacks called for channel '{channel}' with data: {data}")
        if channel in self.callbacks:
            self.logger.debug(f"Found {len(self.callbacks[channel])} callbacks for channel '{channel}'")
            for i, callback in enumerate(self.callbacks[channel]):
                try:
                    self.logger.debug(f"🔔 Executing callback {i+1} for channel '{channel}'")
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                    self.logger.debug(f"🔔 Callback {i+1} executed successfully for channel '{channel}'")
                except Exception as e:
                    self.logger.error(f"Error executing callback for channel '{channel}': {str(e)}")
        else:
            self.logger.warning(f"🔔 No callbacks registered for channel '{channel}'")
    
    async def _process_notification_async(self, conn, pid, channel, payload):
        """
        Async version of process notification for async connections.
        
        Args:
            conn: Database connection
            pid: Process ID that sent the notification
            channel: Notification channel
            payload: Notification payload
        """
        self.logger.debug(f"🔔 _process_notification_async called: channel={channel}, payload={payload}")
        try:
            # Parse JSON payload if it's a string
            if isinstance(payload, str):
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    self.logger.warning(f"Failed to parse JSON payload: {payload}")
                    data = {"raw_payload": payload}
            else:
                data = payload if payload else {}
            
            # Schedule callback execution
            await self._execute_callbacks(channel, data)
            
        except Exception as e:
            self.logger.error(f"Error processing notification: {e}", exc_info=True)
    
    def register_callback(self, channel: str, callback: Callable[[dict], Awaitable[None]]):
        """
        Register a callback for a specific notification channel.
        
        Args:
            channel: The notification channel to register for
            callback: Async function to call when a notification is received
        """
        self.logger.debug(f"🔔 register_callback called for channel '{channel}' with callback: {callback}")
        
        if not callable(callback):
            self.logger.error(f"Callback for channel '{channel}' is not callable: {callback}")
            return
        if channel not in self.callbacks:
            self.callbacks[channel] = []
            self.logger.debug(f"Created new callback list for channel: {channel}")
        self.callbacks[channel].append(callback)
        self.logger.debug(f"Registered callback for channel: {channel} (total callbacks: {len(self.callbacks[channel])})")
        
        # Log all registered callbacks for debugging
        total_callbacks = sum(len(cbs) for cbs in self.callbacks.values())
        self.logger.debug(f"Total callbacks across all channels: {total_callbacks}")
        
        # If we're already listening, dynamically add listener for this channel
        if self.running and self.listen_connection and not self._is_connection_closed(self.listen_connection):
            async def add_channel_listener():
                try:
                    def notification_handler(connection, pid, ch, payload):
                        asyncio.create_task(
                            self._process_notification_async(connection, pid, ch, payload)
                        )
                    await self.listen_connection.add_listener(channel, notification_handler)
                    self.active_channels.add(channel)
                    self.logger.debug(f"🔔 Dynamically added asyncpg listener for channel: {channel}")
                except Exception as e:
                    self.logger.error(f"Error dynamically adding listener for {channel}: {e}")
            asyncio.create_task(add_channel_listener())
    
    async def notify_users_changed(self, signal_type: str = SIGNAL_TYPE_UPDATED):
        """
        Send notification that users list has changed.
        
        Args:
            signal_type: Type of change (created, updated, deleted)
        """
        payload = json.dumps({"type": signal_type, "timestamp": str(asyncio.get_event_loop().time())})
        await self._send_notification(CHANNEL_USERS, payload)
    
    async def notify_spaces_changed(self, signal_type: str = SIGNAL_TYPE_UPDATED):
        """
        Send notification that spaces list has changed.
        
        Args:
            signal_type: Type of change (created, updated, deleted)
        """
        payload = json.dumps({"type": signal_type, "timestamp": str(asyncio.get_event_loop().time())})
        await self._send_notification(CHANNEL_SPACES, payload)
    
    async def notify_graphs_changed(self, signal_type: str = SIGNAL_TYPE_UPDATED):
        """
        Send notification that graphs list has changed.
        
        Args:
            signal_type: Type of change (created, updated, deleted)
        """
        payload = json.dumps({"type": signal_type, "timestamp": str(asyncio.get_event_loop().time())})
        await self._send_notification(CHANNEL_GRAPHS, payload)
    
    async def notify_user_changed(self, user_id: str, signal_type: str = SIGNAL_TYPE_UPDATED):
        """
        Send notification that a specific user has changed.
        
        Args:
            user_id: ID of the user that changed
            signal_type: Type of change (created, updated, deleted)
        """
        payload = json.dumps({
            "type": signal_type,
            "user_id": user_id,
            "timestamp": str(asyncio.get_event_loop().time())
        })
        await self._send_notification(CHANNEL_USER, payload)
    
    async def notify_space_changed(self, space_id: str, signal_type: str = SIGNAL_TYPE_UPDATED):
        """
        Send notification that a specific space has changed.
        
        Args:
            space_id: ID of the space that changed
            signal_type: Type of change (created, updated, deleted)
        """
        payload = json.dumps({
            "type": signal_type,
            "space_id": space_id,
            "timestamp": str(asyncio.get_event_loop().time())
        })
        await self._send_notification(CHANNEL_SPACE, payload)
    
    async def notify_graph_changed(self, graph_uri: str, signal_type: str = SIGNAL_TYPE_UPDATED):
        """
        Send notification that a specific graph has changed.
        
        Args:
            graph_uri: URI of the graph that changed
            signal_type: Type of change (created, updated, deleted)
        """
        payload = json.dumps({
            "type": signal_type,
            "graph_uri": graph_uri,
            "timestamp": str(asyncio.get_event_loop().time())
        })
        await self._send_notification(CHANNEL_GRAPH, payload)

    async def notify_cache_invalidate(self, cache_type: str, space_id: str):
        """
        Send a cache invalidation signal to all instances.
        
        Args:
            cache_type: Which cache to invalidate ("datatype" or "stats")
            space_id: Space whose cache entry should be invalidated
        """
        payload = json.dumps({
            "cache_type": cache_type,
            "space_id": space_id,
            "timestamp": str(asyncio.get_event_loop().time()),
        })
        await self._send_notification(CHANNEL_CACHE_INVALIDATE, payload)
    
    async def _init_notify_connection(self):
        """
        Initialize a dedicated asyncpg connection for sending notifications.
        asyncpg runs in autocommit mode by default — NOTIFY is sent immediately.
        """
        try:
            self.notify_connection = await self._create_dedicated_connection()
            self.logger.info("Initialized dedicated asyncpg NOTIFY connection")
        except Exception as e:
            self.logger.error(f"Failed to initialize notification connection: {e}")
            self.notify_connection = None
            raise

    async def _close_notify_connection(self):
        """
        Close the dedicated NOTIFY connection.
        """
        if self.notify_connection and not self._is_connection_closed(self.notify_connection):
            try:
                await self.notify_connection.close()
                self.logger.info("Closed dedicated NOTIFY connection")
            except Exception as e:
                self.logger.error(f"Error closing notification connection: {str(e)}")
            finally:
                self.notify_connection = None
            
    async def _send_notification(self, channel: str, payload: str):
        """
        Send a notification via PostgreSQL NOTIFY using a dedicated asyncpg connection.
        
        Args:
            channel: The notification channel
            payload: JSON payload to send
        """
        # Use a lock to ensure only one notification is sent at a time
        async with self.notify_lock:
            try:
                # Ensure we have a valid connection
                if self.notify_connection is None or self._is_connection_closed(self.notify_connection):
                    await self._init_notify_connection()
                if self.notify_connection:
                    # Escape single quotes in payload to prevent SQL injection
                    escaped_payload = payload.replace("'", "''")
                    notify_sql = f"NOTIFY {channel}, '{escaped_payload}'"
                    await self.notify_connection.execute(notify_sql)
                    self.logger.info(f"🔔 Sent notification on channel '{channel}': {payload}")
                else:
                    self.logger.error(f"No notification connection available for channel '{channel}'")
            except Exception as e:
                self.logger.error(f"Error sending notification on channel '{channel}': {e}")
                # Reset connection on error so it gets recreated next time
                try:
                    if self.notify_connection and not self._is_connection_closed(self.notify_connection):
                        await self.notify_connection.close()
                except Exception:
                    pass
                self.notify_connection = None
