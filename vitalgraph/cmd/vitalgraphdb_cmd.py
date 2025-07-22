#!/usr/bin/env python3
"""
VitalGraphDB Command Line Interface

This module provides the command-line interface for VitalGraphDB server.
It handles argument parsing and delegates to the main server functionality.
"""

import argparse
import os
import sys
from typing import Optional

def parse_args() -> argparse.Namespace:
    """Parse command line arguments for VitalGraphDB server."""
    parser = argparse.ArgumentParser(
        description="VitalGraphDB - A high-performance RDF graph database server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vitalgraphdb                          # Start server with default settings
  vitalgraphdb --port 8080              # Start server on port 8080
  vitalgraphdb --host 127.0.0.1         # Start server on localhost only
  vitalgraphdb --host 0.0.0.0 --port 9000  # Start server on all interfaces, port 9000
        """
    )
    
    parser.add_argument(
        "--host",
        type=str,
        help="Host to bind the server to (overrides HOST environment variable). Default: 0.0.0.0"
    )
    
    parser.add_argument(
        "--port", "-p",
        type=int,
        help="Port to bind the server to (overrides PORT environment variable). Default: 8001"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="VitalGraphDB 1.0.0"
    )
    
    return parser.parse_args()

def main():
    """Main entry point for VitalGraphDB command-line interface."""
    # Parse command line arguments
    args = parse_args()
    
    # Override environment variables with command line arguments if provided
    if args.host is not None:
        os.environ["HOST"] = args.host
        print(f"Host set to: {args.host}")
    
    if args.port is not None:
        os.environ["PORT"] = str(args.port)
        print(f"Port set to: {args.port}")
    
    # Import and call the original main functionality
    try:
        from vitalgraph.main.main import run_server
        print("Starting VitalGraphDB server...")
        run_server()
    except ImportError as e:
        print(f"Error importing VitalGraphDB main module: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutting down VitalGraphDB server...")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting VitalGraphDB server: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
