#!/usr/bin/env python3
"""
Aggressive Resource Cleanup for VitalGraph

This module provides utilities for aggressively cleaning up asyncio resources
to completely eliminate ResourceWarning messages.
"""

import asyncio
import gc
import logging
import weakref
from typing import Set, List, Any
import aiohttp
import asyncpg

logger = logging.getLogger(__name__)


class AggressiveResourceCleaner:
    """
    Aggressive resource cleaner that tracks and forcibly closes all asyncio resources.
    
    This is a more aggressive approach than the standard ResourceManager,
    designed to eliminate all ResourceWarning messages.
    """
    
    def __init__(self):
        self._all_objects: Set[Any] = set()
        self._cleanup_hooks: List[callable] = []
        
    def register_object(self, obj: Any) -> Any:
        """Register any object for aggressive cleanup tracking."""
        if obj:
            self._all_objects.add(obj)
        return obj
    
    def add_cleanup_hook(self, hook: callable) -> None:
        """Add a cleanup hook to be called during aggressive cleanup."""
        self._cleanup_hooks.append(hook)
    
    async def aggressive_cleanup(self) -> None:
        """Perform aggressive cleanup of all tracked resources and system-wide cleanup."""
        logger.info("🧹 Starting aggressive resource cleanup...")
        
        # Run custom cleanup hooks first
        for hook in self._cleanup_hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
            except Exception as e:
                logger.debug(f"Error in cleanup hook: {e}")
        
        # Close all tracked objects
        closed_count = 0
        for obj in list(self._all_objects):
            try:
                if hasattr(obj, 'close') and callable(obj.close):
                    if asyncio.iscoroutinefunction(obj.close):
                        await obj.close()
                    else:
                        obj.close()
                    closed_count += 1
                elif hasattr(obj, 'terminate') and callable(obj.terminate):
                    obj.terminate()
                    closed_count += 1
            except Exception as e:
                logger.debug(f"Error closing tracked object {obj}: {e}")
        
        logger.info(f"🧹 Closed {closed_count} tracked objects")
        
        # Clear tracking
        self._all_objects.clear()
        self._cleanup_hooks.clear()
        
        # Force multiple garbage collection cycles
        for i in range(3):
            gc.collect()
            await asyncio.sleep(0.1)
        
        # Cancel all remaining tasks except current one
        current_task = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task != current_task and not task.done()]
        
        if tasks:
            logger.info(f"🧹 Cancelling {len(tasks)} remaining tasks")
            for task in tasks:
                task.cancel()
            
            # Wait for tasks to be cancelled
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("🧹 Some tasks didn't cancel within timeout")
        
        # Final cleanup delays
        await asyncio.sleep(0.5)
        gc.collect()
        await asyncio.sleep(0.2)
        
        logger.info("🧹 Aggressive resource cleanup completed")


# Global aggressive cleaner instance
_aggressive_cleaner = AggressiveResourceCleaner()


def get_aggressive_cleaner() -> AggressiveResourceCleaner:
    """Get the global aggressive resource cleaner instance."""
    return _aggressive_cleaner


async def aggressive_cleanup() -> None:
    """Perform aggressive cleanup of all resources globally."""
    await _aggressive_cleaner.aggressive_cleanup()


def track_for_aggressive_cleanup(obj: Any) -> Any:
    """Track an object for aggressive cleanup."""
    return _aggressive_cleaner.register_object(obj)


def add_aggressive_cleanup_hook(hook: callable) -> None:
    """Add a cleanup hook for aggressive cleanup."""
    _aggressive_cleaner.add_cleanup_hook(hook)
