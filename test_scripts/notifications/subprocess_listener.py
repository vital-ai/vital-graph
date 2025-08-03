#!/usr/bin/env python3
"""
Subprocess notification listener for VitalGraph.
This script runs as a separate process to listen for PostgreSQL notifications.
"""

import asyncio
import logging
import sys
import signal
import json
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.signal.signal_manager import (
    CHANNEL_SPACE, CHANNEL_SPACES, CHANNEL_GRAPH, 
    CHANNEL_GRAPHS, CHANNEL_USER, CHANNEL_USERS
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables for cleanup
receiver_impl = None
running = True

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global running
    logger.info("🛑 SUBPROCESS: Shutdown signal received")
    running = False

# Notification callback handlers
async def space_notification_callback(data):
    """Callback for space notifications."""
    logger.info(f"🔔 SUBPROCESS: SPACE NOTIFICATION RECEIVED! Data: {data}")

async def spaces_notification_callback(data):
    """Callback for spaces list notifications."""
    logger.info(f"🔔 SUBPROCESS: SPACES NOTIFICATION RECEIVED! Data: {data}")

async def graph_notification_callback(data):
    """Callback for graph notifications."""
    logger.info(f"🔔 SUBPROCESS: GRAPH NOTIFICATION RECEIVED! Data: {data}")

async def graphs_notification_callback(data):
    """Callback for graphs list notifications."""
    logger.info(f"🔔 SUBPROCESS: GRAPHS NOTIFICATION RECEIVED! Data: {data}")

async def user_notification_callback(data):
    """Callback for user notifications."""
    logger.info(f"🔔 SUBPROCESS: USER NOTIFICATION RECEIVED! Data: {data}")

async def users_notification_callback(data):
    """Callback for users list notifications."""
    logger.info(f"🔔 SUBPROCESS: USERS NOTIFICATION RECEIVED! Data: {data}")

async def main():
    """Main subprocess listener function."""
    global receiver_impl, running
    
    try:
        logger.info("🚀 SUBPROCESS: Starting notification listener...")
        
        # Load configuration with explicit path
        config_path = "/Users/hadfield/Local/vital-git/vital-graph/vitalgraphdb_config/vitalgraphdb-config.yaml"
        logger.info(f"SUBPROCESS: Loading config from {config_path}")
        config = VitalGraphConfig(config_path)
        logger.info("✅ SUBPROCESS: Configuration loaded")
        
        # Create receiver VitalGraphImpl instance
        receiver_impl = VitalGraphImpl(config)
        await receiver_impl.connect_database()
        logger.info("✅ SUBPROCESS: Database connected")
        
        # Get SignalManager
        signal_manager = receiver_impl.get_signal_manager()
        if not signal_manager:
            logger.error("❌ SUBPROCESS: No SignalManager available")
            return
        
        logger.info("✅ SUBPROCESS: SignalManager obtained")
        
        # Register callbacks for all channels
        signal_manager.register_callback(CHANNEL_SPACE, space_notification_callback)
        signal_manager.register_callback(CHANNEL_SPACES, spaces_notification_callback)
        signal_manager.register_callback(CHANNEL_GRAPH, graph_notification_callback)
        signal_manager.register_callback(CHANNEL_GRAPHS, graphs_notification_callback)
        signal_manager.register_callback(CHANNEL_USER, user_notification_callback)
        signal_manager.register_callback(CHANNEL_USERS, users_notification_callback)
        
        logger.info("✅ SUBPROCESS: All notification callbacks registered")
        
        # Start listening for notifications
        await signal_manager.start_listening()
        logger.info("🎧 SUBPROCESS: Notification listener started")
        
        # Keep the subprocess running
        logger.info("🎧 SUBPROCESS: Listening for notifications... (Press Ctrl+C to stop)")
        
        while running:
            await asyncio.sleep(1.0)
            
    except KeyboardInterrupt:
        logger.info("🛑 SUBPROCESS: Keyboard interrupt received")
    except Exception as e:
        logger.error(f"❌ SUBPROCESS: Error in main: {e}")
        import traceback
        logger.error(f"SUBPROCESS: Traceback: {traceback.format_exc()}")
    finally:
        # Cleanup
        logger.info("🧹 SUBPROCESS: Cleaning up...")
        if receiver_impl:
            try:
                signal_manager = receiver_impl.get_signal_manager()
                if signal_manager:
                    await signal_manager.stop_listening()
                    logger.info("✅ SUBPROCESS: SignalManager stopped")
                
                # VitalGraphImpl doesn't have disconnect_database, use db_impl
                if receiver_impl.db_impl:
                    await receiver_impl.db_impl.disconnect()
                    logger.info("✅ SUBPROCESS: Database disconnected")
            except Exception as e:
                logger.error(f"❌ SUBPROCESS: Error during cleanup: {e}")
        
        print("👋 SUBPROCESS: Listener stopped", flush=True)
        logger.info("👋 SUBPROCESS: Listener stopped")

if __name__ == "__main__":
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run the main function
    asyncio.run(main())
