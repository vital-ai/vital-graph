#!/usr/bin/env python3
"""
VitalGraph Notification System Listener
======================================

This script sets up a notification listener for VitalGraph:
1. Sets up a VitalGraphImpl instance and SignalManager
2. Lists the available spaces without making changes
3. Listens indefinitely for notifications on all channels
4. Prints notifications as they arrive in real-time

Press Ctrl+C to exit the listener.
"""

import asyncio
import logging
import signal
import sys
import time
import random
import subprocess
import threading
import os
from pathlib import Path
from typing import Dict, Any

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables for cleanup
sender_impl = None
listener_process = None
running = True
exit_event = asyncio.Event()

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global running, listener_process
    logger.info("\n⛔ Shutdown signal received, cleaning up...")
    if listener_process:
        # Note: Notification callbacks are now handled in the subprocess_listener.py script
        listener_process.terminate()
    exit_event.set()

def read_subprocess_output(process):
    """Read and log subprocess output in a separate thread."""
    try:
        for line in iter(process.stdout.readline, ''):
            if line:
                print(f"SUBPROCESS: {line.rstrip()}")
    except Exception as e:
        logger.error(f"Error reading subprocess output: {e}")

async def setup_connection():
    """Setup subprocess listener and sender connection."""
    global sender_impl, listener_process
    
    try:
        logger.info("🚀 Starting subprocess notification test...")
        
        # Start the subprocess listener
        listener_script = Path(__file__).parent / "subprocess_listener.py"
        python_path = "/opt/homebrew/anaconda3/envs/vital-graph/bin/python"
        
        logger.info("🎧 Starting subprocess listener...")
        listener_process = subprocess.Popen(
            [python_path, str(listener_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # Start a thread to read subprocess output
        output_thread = threading.Thread(target=read_subprocess_output, args=(listener_process,))
        output_thread.daemon = True
        output_thread.start()
        
        logger.info(f"✅ Subprocess listener started with PID: {listener_process.pid}")
        
        # Wait for subprocess to initialize
        logger.info("⏳ Waiting 5 seconds for subprocess listener to fully initialize...")
        await asyncio.sleep(5.0)
        
        # Load configuration for sender
        config_loader = VitalGraphConfig("/Users/hadfield/Local/vital-git/vital-graph/vitalgraphdb_config/vitalgraphdb-config.yaml")
        logger.info("✅ Configuration loaded for sender")
        
        # Create sender VitalGraphImpl instance (completely separate process from listener)
        logger.info("🔍 Creating sender database connection...")
        sender_impl = VitalGraphImpl(config=config_loader)
        await sender_impl.connect_database()
        logger.info("✅ Sender database connection and SpaceManager established")
        
        logger.info("✅ Connection setup complete. Subprocess listener and sender process initialized.")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error setting up connections: {e}")
        import traceback
        traceback.print_exc()
        return False

async def cleanup_connections():
    """Clean up subprocess and sender database connections."""
    global sender_impl, listener_process
    
    logger.info("\n🧹 Cleaning up subprocess and sender connections...")
    
    if listener_process:
        logger.info("Terminating subprocess listener...")
        listener_process.terminate()
        try:
            listener_process.wait(timeout=5)
            logger.info("✅ Subprocess terminated gracefully")
        except subprocess.TimeoutExpired:
            logger.warning("⚠️ Subprocess did not terminate gracefully, killing...")
            listener_process.kill()
            listener_process.wait()
    
    if sender_impl:
        logger.info("Disconnecting sender from database...")
        try:
            # VitalGraphImpl doesn't have disconnect_database, disconnect via db_impl
            if sender_impl.db_impl:
                await sender_impl.db_impl.disconnect()
                logger.info("✅ Sender database disconnected")
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
    
    logger.info("✅ Cleanup complete")

async def list_spaces():
    """List available spaces using sender connection."""
    logger.info("\n🔍 Listing available spaces...")
    
    try:
        if not sender_impl:
            logger.error("❌ Sender VitalGraphImpl not available")
            return
            
        space_manager = sender_impl.get_space_manager()
        spaces = space_manager.list_spaces()
        space_names = [space.get_space_id() for space in spaces if hasattr(space, 'get_space_id')]
        logger.info(f"📋 Available spaces: {space_names}")
        
    except Exception as e:
        logger.error(f"❌ Error listing spaces: {e}")
        return False

async def create_test_space():
    """Create a test space using sender to trigger notifications."""
    logger.info("\n🏗️ SENDER: Creating test space to trigger notifications...")
    
    try:
        # Generate a unique space ID with timestamp (keep under 15 chars)
        import time
        timestamp = int(time.time())
        # Use last 6 digits of timestamp to keep space ID short
        short_timestamp = str(timestamp)[-6:]
        test_space_id = f"sep_{short_timestamp}"
        
        # Create space data
        space_data = {
            'tenant': 'test_tenant',
            'space': test_space_id,
            'space_name': f'Separate Pool Test Space {timestamp}',
            'space_description': 'Test space created to verify notification flow between separate pools'
        }
        
        logger.info(f"📝 SENDER: Creating space with data: {space_data}")
        
        # Use sender's SpaceManager to create space with tables (this sends notifications)
        if not sender_impl:
            logger.error("❌ SENDER: VitalGraphImpl not available")
            return None
            
        space_manager = sender_impl.get_space_manager()
        success = await space_manager.create_space_with_tables(
            space_id=test_space_id,
            space_name=space_data['space_name'],
            space_description=space_data['space_description']
        )
        
        if success:
            logger.info(f"✅ SENDER: Successfully created test space: {test_space_id}")
            logger.info(f"📄 SENDER: Space created with tables and notifications sent to receiver!")
            return test_space_id
        else:
            logger.error(f"❌ SENDER: Failed to create test space: {test_space_id}")
            return None
            
    except Exception as e:
        logger.error(f"❌ SENDER: Error creating test space: {e}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    """Main subprocess notification test."""
    global sender_impl, listener_process
    
    try:
        logger.info("🧪 VitalGraph Subprocess Notification Test")
        logger.info("=" * 50)
        
        # Set up signal handlers for clean shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Setup connection (this now starts subprocess and creates sender)
        setup_success = await setup_connection()
        if not setup_success:
            logger.error("❌ Setup failed, exiting")
            return
        
        # List spaces to verify configuration
        await list_spaces()
        
        # Wait a moment for the listener to be fully ready
        logger.info("\n⏳ Waiting additional 2 seconds to ensure listener is fully ready...")
        await asyncio.sleep(2.0)
        
        # Create a test space to trigger notifications
        test_space_id = await create_test_space()
        if test_space_id:
            logger.info(f"\n🎯 Test space '{test_space_id}' created - watch for notifications!")
        else:
            logger.warning("\n⚠️ Test space creation failed - continuing with listener only")
        
        logger.info("\n🎧 Subprocess is listening for notifications...")
        logger.info("Press Ctrl+C to exit the test.")
        
        # Keep the main process running while subprocess listens
        while listener_process and listener_process.poll() is None:
            await asyncio.sleep(1.0)
            print(".", end="", flush=True)
            
    finally:
        # Cleanup
        await cleanup_connections()
        
    logger.info("\n👋 Subprocess notification test completed")
    logger.info("Check the subprocess output above for notification reception logs.")

if __name__ == "__main__":
    asyncio.run(main())
