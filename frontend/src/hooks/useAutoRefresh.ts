import { useEffect } from 'react';
import { useChangeNotification } from '../contexts/ChangeNotificationContext';

export interface AutoRefreshOptions {
  onRefresh: () => void | Promise<void>;
  entityType?: 'users' | 'spaces' | 'user' | 'space';
  entityId?: string;
}

/**
 * Hook to automatically refresh data when relevant change notifications are received
 * 
 * This hook is designed for list pages and detail pages that should auto-refresh
 * when they are not in editing mode.
 */
export const useAutoRefresh = (options: AutoRefreshOptions) => {
  const { onRefresh, entityType, entityId } = options;
  const { setOnDataRefresh, currentPage } = useChangeNotification();

  useEffect(() => {
    // Set up the refresh callback for this component
    const handleRefresh = async () => {
      try {
        await onRefresh();
      } catch (error) {
        console.error('Auto-refresh failed:', error);
      }
    };

    setOnDataRefresh(handleRefresh);

    // Cleanup on unmount
    return () => {
      setOnDataRefresh(() => {});
    };
  }, [onRefresh, setOnDataRefresh]);

  // Update current page info if specific entity type/ID provided
  useEffect(() => {
    if (entityType && entityId) {
      // This is for detail pages - the route should already set this,
      // but we can ensure it's correct
      const pageInfo = {
        page: currentPage.page,
        entityType: entityType === 'user' || entityType === 'space' ? entityType : undefined,
        entityId: entityId,
        isEditing: currentPage.isEditing
      };
      
      // Only update if different to avoid infinite loops
      if (currentPage.entityType !== pageInfo.entityType || 
          currentPage.entityId !== pageInfo.entityId) {
        // Note: We don't call setCurrentPage here to avoid overriding route-based updates
        console.log('Auto-refresh hook detected entity info:', pageInfo);
      }
    }
  }, [entityType, entityId, currentPage]);
};
