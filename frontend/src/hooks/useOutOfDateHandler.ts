import { useEffect, useState } from 'react';
import { useChangeNotification } from '../contexts/ChangeNotificationContext';

export interface OutOfDateHandlerOptions {
  entityType?: 'user' | 'space';
  entityId?: string;
  onRefresh?: (data: any) => void;
  onCancel?: () => void;
}

export interface OutOfDateHandlerResult {
  isOutOfDate: boolean;
  isEditing: boolean;
  startEditing: () => void;
  stopEditing: () => void;
  handleRefresh: () => Promise<void>;
  handleCancel: () => void;
  dismissOutOfDate: () => void;
}

/**
 * Hook to handle out-of-date state for editing components
 * 
 * This hook manages the editing state and handles out-of-date notifications
 * when the entity being edited has been changed by another user/process.
 */
export const useOutOfDateHandler = (options: OutOfDateHandlerOptions = {}): OutOfDateHandlerResult => {
  const {
    currentPage,
    outOfDateState,
    setEditingState,
    refreshCurrentData,
    dismissOutOfDate,
    setOnDataRefresh
  } = useChangeNotification();
  
  const [isEditing, setIsEditing] = useState(false);
  const { entityType, entityId, onRefresh, onCancel } = options;

  // Set up data refresh callback
  useEffect(() => {
    if (onRefresh) {
      setOnDataRefresh(onRefresh);
    }
    
    // Cleanup callback on unmount
    return () => {
      setOnDataRefresh(() => {});
    };
  }, [onRefresh, setOnDataRefresh]);

  // Check if the out-of-date state applies to this component
  const isRelevantOutOfDate = () => {
    if (!outOfDateState.isOutOfDate || !outOfDateState.affectedEntity) {
      return false;
    }
    
    // If specific entity type/ID provided, check if they match
    if (entityType && entityId) {
      return outOfDateState.affectedEntity.type === entityType &&
             outOfDateState.affectedEntity.id === entityId;
    }
    
    // Otherwise, check against current page
    return currentPage.entityType === outOfDateState.affectedEntity.type &&
           currentPage.entityId === outOfDateState.affectedEntity.id;
  };

  const startEditing = () => {
    setIsEditing(true);
    setEditingState(true);
  };

  const stopEditing = () => {
    setIsEditing(false);
    setEditingState(false);
    dismissOutOfDate();
  };

  const handleRefresh = async () => {
    try {
      await refreshCurrentData();
      dismissOutOfDate();
      // Keep editing state if user wants to continue editing after refresh
    } catch (error) {
      console.error('Failed to refresh data:', error);
      throw error;
    }
  };

  const handleCancel = () => {
    stopEditing();
    if (onCancel) {
      onCancel();
    }
  };

  return {
    isOutOfDate: isRelevantOutOfDate(),
    isEditing,
    startEditing,
    stopEditing,
    handleRefresh,
    handleCancel,
    dismissOutOfDate,
  };
};
