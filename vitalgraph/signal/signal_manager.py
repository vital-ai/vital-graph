
import asyncio
import json
import logging
import psycopg
import threading
from asyncio import Task
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Callable, Any, Set, Union, Awaitable

logger = logging.getLogger(__name__)

# Constants for notification channels
CHANNEL_USERS = "vitalgraph_users"
CHANNEL_SPACES = "vitalgraph_spaces"
CHANNEL_GRAPHS = "vitalgraph_graphs"
CHANNEL_USER = "vitalgraph_user"
CHANNEL_SPACE = "vitalgraph_space" 
CHANNEL_GRAPH = "vitalgraph_graph"

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
            CHANNEL_GRAPH: []
        }
        
        # Set of channels we're currently listening to
        self.active_channels: Set[str] = set()
        
        # Register default logging callbacks for all channels
        self._register_default_logging_callbacks()
    
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
            # psycopg3 async connections have .closed attribute
            if hasattr(connection, 'closed'):
                return connection.closed
            # Some connection types might have is_closed() method
            elif hasattr(connection, 'is_closed'):
                return connection.is_closed()
            # Some connection types might have _closed attribute
            elif hasattr(connection, '_closed'):
                return connection._closed
            else:
                # If we can't determine, assume it's open
                return False
        except Exception:
            # If any error occurs checking status, assume closed
            return True
    
    def _commit_connection(self, connection) -> bool:
        """
        Commit a transaction on a connection, handling different connection types.
        
        Args:
            connection: Database connection object
            
        Returns:
            bool: True if commit succeeded, False otherwise
        """
        if connection is None:
            return False
            
        # Handle different connection types
        try:
            # Most connections have commit() method
            if hasattr(connection, 'commit'):
                connection.commit()
                return True
            # Some async connections might use different methods
            elif hasattr(connection, 'commit_async'):
                connection.commit_async()
                return True
            # Some connections might auto-commit
            else:
                # If no commit method, assume auto-commit or not needed
                return True
        except Exception as e:
            self.logger.debug(f"Error committing connection: {e}")
            return False
    
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
            self.listen_connection.close()
            self.listen_connection = None
            
        # Close notify connection
        await self._close_notify_connection()
            
        self.logger.info("PostgreSQL notification listener stopped")
    
    async def _listen_for_notifications(self):
        """Background task that listens for PostgreSQL notifications."""
        retry_delay = 1
        max_retry_delay = 30
        
        while self.running:
            self.listen_connection = None
            try:
                # Create a dedicated connection for notifications (not from pool)
                self.logger.debug("Creating dedicated connection for notifications")
                # Get database config - handle both dict and VitalGraphConfig object
                if hasattr(self.db_impl.config, 'get_database_config'):
                    db_config = self.db_impl.config.get_database_config()
                else:
                    # Assume it's already a dict with database config
                    db_config = self.db_impl.config
                conn_str = f"postgresql://{db_config['username']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
                
                import psycopg
                # Use async connection for proper notification handling
                self.listen_connection = await psycopg.AsyncConnection.connect(conn_str)
                self.logger.debug(f"Got dedicated async connection: {self.listen_connection}")
                await self.listen_connection.set_autocommit(True)
                
                # Reset retry delay on successful connection
                retry_delay = 1
                
                # Note: We don't need add_notify_handler since we're actively consuming notifies()
                # The active consumption pattern is more reliable than passive handlers
                self.logger.info("🔔 DEBUG: Using active notification consumption (no handler needed)")
                
                # DEBUG: Show exactly what channels we have
                all_channels = list(self.callbacks.keys())
                self.logger.debug(f"🔔 SignalManager has {len(all_channels)} channels: {all_channels}")
                
                # Listen on all channels using async cursor
                for channel in self.callbacks.keys():
                    try:
                        async with self.listen_connection.cursor() as cursor:
                            await cursor.execute(f"LISTEN {channel}")
                        self.logger.debug(f"🔔 Executed LISTEN {channel} on async connection")
                    except Exception as e:
                        self.logger.error(f"Error executing LISTEN {channel}: {e}")
                        self.logger.error(f"🔔 Error executing LISTEN {channel}: {e}")
                    
                self.active_channels = set(self.callbacks.keys())
                
                self.logger.info(f"PostgreSQL notification listener connected, listening on {len(self.active_channels)} channels")
                self.logger.debug(f"🔔 Listening setup complete. Registered callbacks: {list(self.callbacks.keys())}")
                self.logger.debug(f"🔔 Connection supports notifies: {hasattr(self.listen_connection, 'notifies')}")
                self.logger.debug(f"🔔 Final channel list: {list(self.active_channels)}")
                
                # Keep connection alive until we're told to stop
                self.logger.info("Notification listener running - keeping connection alive")
                self.logger.info(f" Starting notification listener loop")
                
                # Create the async generator ONCE and reuse it across iterations
                # to avoid creating/discarding generator objects every second
                gen = self.listen_connection.notifies()
                debug_counter = 0
                
                while self.running:
                    try:
                        try:
                            # Wait for notification with timeout using the persistent generator
                            notify = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
                            
                            self.logger.debug(f"🔔 Notification received: channel={notify.channel}, payload={notify.payload}, pid={notify.pid}")
                            
                            # Process the notification through our handler
                            await self._process_notification_async(self.listen_connection, notify.pid, notify.channel, notify.payload)
                            
                        except asyncio.TimeoutError:
                            # Timeout is expected - no notifications in the last second
                            pass
                        except StopAsyncIteration:
                            # Generator exhausted, recreate it
                            gen = self.listen_connection.notifies()
                        
                        debug_counter += 1
                        if debug_counter % 10 == 0:  # Log every 10 seconds
                            self.logger.debug(f"🔔 Listener still running, callbacks registered: {sum(len(cbs) for cbs in self.callbacks.values())}")
                            
                    except Exception as e:
                        self.logger.error(f"Error in notification listener loop: {str(e)}")
                        import traceback
                        self.logger.error(f"Traceback: {traceback.format_exc()}")
                        break
                    
            except Exception as e:
                self.logger.error(f"Error in notification listener: {str(e)}")
                
                # Clear active channels
                self.active_channels.clear()
                
                # Clean up async connection if it exists
                if hasattr(self, 'listen_connection') and self.listen_connection:
                    try:
                        if not self._is_connection_closed(self.listen_connection):
                            self.logger.debug("Closing async connection after error")
                            await self.listen_connection.close()
                    except Exception:
                        pass
                    self.listen_connection = None
                
            finally:
                # Clean up dedicated async connection
                if hasattr(self, 'listen_connection') and self.listen_connection:
                    try:
                        if not self._is_connection_closed(self.listen_connection):
                            self.logger.debug("Closing dedicated async notification connection")
                            await self.listen_connection.close()
                    except Exception as e:
                        self.logger.error(f"Error closing dedicated connection: {e}")
                    finally:
                        self.listen_connection = None
                        
            # Only retry if we're still supposed to be running
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
                    import json
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    self.logger.warning(f"Failed to parse JSON payload: {payload}")
                    data = {"raw_payload": payload}
            else:
                data = payload if payload else {}
            
            # Schedule callback execution
            await self._execute_callbacks(channel, data)
            
        except Exception as e:
            self.logger.error(f"Error processing notification: {str(e)}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
    
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
        
        # If we're already listening, make sure we're listening on this channel
        if self.running and self.listen_connection and not self._is_connection_closed(self.listen_connection):
            # Use async cursor for LISTEN command
            async def listen_on_channel():
                async with self.listen_connection.cursor() as cursor:
                    await cursor.execute(f"LISTEN {channel}")
            asyncio.create_task(listen_on_channel())
            self.logger.debug(f"🔔 Executed LISTEN {channel} on async connection")
    
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
    
    async def _init_notify_connection(self):
        """
        Initialize a persistent connection for sending notifications.
        """
        try:
            # Handle different backend types
            if hasattr(self.db_impl, 'rdf_pool'):
                # Standard PostgreSQL backend
                self.notify_connection = self.db_impl.rdf_pool.getconn()
            elif hasattr(self.db_impl, 'connection_pool'):
                # Hybrid FusekiPostgreSQLDbImpl backend
                self.notify_connection = await self.db_impl.connection_pool.acquire()
            else:
                raise AttributeError(f"Backend {type(self.db_impl)} doesn't have a supported connection pool")
            
            self.logger.info(f"Initialized persistent notification connection ID: {id(self.notify_connection)}")
        except Exception as e:
            self.logger.error(f"Failed to initialize notification connection: {str(e)}")
            self.notify_connection = None
            raise

    async def _close_notify_connection(self):
        """
        Close the persistent notification connection.
        """
        if self.notify_connection and not self._is_connection_closed(self.notify_connection):
            try:
                # Handle different backend types
                if hasattr(self.db_impl, 'rdf_pool'):
                    # Standard PostgreSQL backend - no await needed for this pool
                    self.db_impl.rdf_pool.putconn(self.notify_connection)
                elif hasattr(self.db_impl, 'connection_pool'):
                    # Hybrid FusekiPostgreSQLDbImpl backend - await needed for asyncpg pool
                    await self.db_impl.connection_pool.release(self.notify_connection)
                
                self.logger.info("Closed persistent notification connection")
            except Exception as e:
                self.logger.error(f"Error closing notification connection: {str(e)}")
            finally:
                self.notify_connection = None
            
    async def _send_notification(self, channel: str, payload: str):
        """
        Send a notification via PostgreSQL NOTIFY using an async connection.
        
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
                    self.logger.info(f"🔔 Using notification connection ID: {id(self.notify_connection)}")
                    # Send the notification - PostgreSQL NOTIFY requires payload to be embedded directly
                    # Escape single quotes in payload to prevent SQL injection
                    escaped_payload = payload.replace("'", "''")
                    notify_sql = f"NOTIFY {channel}, '{escaped_payload}'"
                    self.logger.info(f"🔔 Executing SQL: {notify_sql}")
                    # Use synchronous execute for the pooled connection
                    self.notify_connection.execute(notify_sql)
                    # Commit the transaction to ensure notification is sent
                    self._commit_connection(self.notify_connection)
                    self.logger.info(f"🔔 Sent notification on channel '{channel}': {payload}")
                else:
                    self.logger.error(f"No notification connection available for channel '{channel}'")
            except Exception as e:
                self.logger.error(f"Error sending notification on channel '{channel}': {str(e)}")
