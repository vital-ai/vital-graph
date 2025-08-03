#!/usr/bin/env python3
"""
Minimal PostgreSQL NOTIFY/LISTEN test to isolate the problem.
Run with: python minimal_notify_test.py listen
Then in another terminal: python minimal_notify_test.py send
"""

import asyncio
import psycopg
import sys
import argparse
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.config.config_loader import VitalGraphConfig

async def listener():
    """Listen for notifications using the exact same pattern as our SignalManager."""
    print("🎧 MINIMAL LISTENER: Starting...")
    
    # Load config exactly like SignalManager
    config = VitalGraphConfig("/Users/hadfield/Local/vital-git/vital-graph/vitalgraphdb_config/vitalgraphdb-config.yaml")
    if hasattr(config, 'get_database_config'):
        db_config = config.get_database_config()
    else:
        db_config = config
    
    conn_str = f"postgresql://{db_config['username']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
    
    try:
        # Use async connection exactly like SignalManager
        conn = await psycopg.AsyncConnection.connect(conn_str)
        await conn.set_autocommit(True)
        print("✅ MINIMAL LISTENER: Connected to database")
        
        # Listen on test channels
        async with conn.cursor() as cursor:
            await cursor.execute("LISTEN test_channel")
            await cursor.execute("LISTEN vitalgraph_spaces")
            await cursor.execute("LISTEN vitalgraph_space")
        print("🎧 MINIMAL LISTENER: Listening on test_channel, vitalgraph_spaces, vitalgraph_space")
        
        # Use the exact same notification consumption pattern as SignalManager
        counter = 0
        while True:
            try:
                # Use async generator pattern for notifications
                gen = conn.notifies()
                try:
                    # Wait for notification with timeout
                    notify = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
                    print(f"🔔 MINIMAL LISTENER: NOTIFICATION RECEIVED! Channel: {notify.channel}, Payload: {notify.payload}")
                    print(f"🔔 MINIMAL LISTENER: PID: {notify.pid}")
                except asyncio.TimeoutError:
                    # Timeout is expected - no notifications in the last second
                    pass
                except StopAsyncIteration:
                    # No more notifications
                    pass
                
                # Periodic heartbeat
                counter += 1
                if counter % 10 == 0:
                    print(f"🎧 MINIMAL LISTENER: Still listening... ({counter} seconds)")
                    
            except KeyboardInterrupt:
                print("🛑 MINIMAL LISTENER: Interrupted by user")
                break
                
    except Exception as e:
        print(f"❌ MINIMAL LISTENER: Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'conn' in locals():
            await conn.close()
        print("👋 MINIMAL LISTENER: Stopped")

async def sender():
    """Send notifications using the exact same pattern as our SignalManager."""
    print("📤 MINIMAL SENDER: Starting...")
    
    # Load config exactly like SignalManager
    config = VitalGraphConfig("/Users/hadfield/Local/vital-git/vital-graph/vitalgraphdb_config/vitalgraphdb-config.yaml")
    if hasattr(config, 'get_database_config'):
        db_config = config.get_database_config()
    else:
        db_config = config
    
    conn_str = f"postgresql://{db_config['username']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
    
    try:
        # Use sync connection like our sender
        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        print("✅ MINIMAL SENDER: Connected to database")
        
        # Send test notifications
        for i in range(5):
            test_payload = f'{{"test": "message_{i+1}", "timestamp": "{i+1}"}}'
            spaces_payload = f'{{"type": "created", "timestamp": "{i+1}"}}'
            space_payload = f'{{"type": "created", "space_id": "test_{i+1}", "timestamp": "{i+1}"}}'
            
            # Send on all channels
            conn.execute(f"NOTIFY test_channel, '{test_payload}'")
            conn.execute(f"NOTIFY vitalgraph_spaces, '{spaces_payload}'")
            conn.execute(f"NOTIFY vitalgraph_space, '{space_payload}'")
            
            print(f"📤 MINIMAL SENDER: Sent notification {i+1}")
            await asyncio.sleep(2)
            
    except Exception as e:
        print(f"❌ MINIMAL SENDER: Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'conn' in locals():
            conn.close()
        print("👋 MINIMAL SENDER: Stopped")

async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Minimal NOTIFY/LISTEN test')
    parser.add_argument('mode', choices=['listen', 'send'], help='Run as listener or sender')
    args = parser.parse_args()
    
    if args.mode == 'listen':
        await listener()
    else:
        await sender()

if __name__ == "__main__":
    asyncio.run(main())
