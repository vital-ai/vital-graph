import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { useWebSocket } from './WebSocketContext';
import { apiService } from '../services/ApiService';

// Define types for change notifications
export interface ChangeMessage {
  type: 'change';
  group: 'users' | 'spaces' | 'user' | 'space';
  userId?: string;
  spaceId?: string;
  timestamp?: string;
}

// Define current page context
export interface CurrentPageInfo {
  page: string;
  entityType?: 'user' | 'space';
  entityId?: string;
  isEditing?: boolean;
}

// Define out-of-date state
export interface OutOfDateState {
  isOutOfDate: boolean;
  affectedEntity?: {
    type: 'user' | 'space';
    id: string;
  };
}

interface ChangeNotificationContextType {
  currentPage: CurrentPageInfo;
  outOfDateState: OutOfDateState;
  setCurrentPage: (page: CurrentPageInfo) => void;
  setEditingState: (isEditing: boolean) => void;
  refreshCurrentData: () => Promise<void>;
  dismissOutOfDate: () => void;
  onDataRefresh?: (data: unknown) => void;
  setOnDataRefresh: (callback: (data: unknown) => void) => void;
}

const ChangeNotificationContext = createContext<ChangeNotificationContextType>({
  currentPage: { page: '/' },
  outOfDateState: { isOutOfDate: false },
  setCurrentPage: () => {},
  setEditingState: () => {},
  refreshCurrentData: async () => {},
  dismissOutOfDate: () => {},
  setOnDataRefresh: () => {},
});

export const useChangeNotification = () => useContext(ChangeNotificationContext);

interface ChangeNotificationProviderProps {
  children: ReactNode;
}

export const ChangeNotificationProvider: React.FC<ChangeNotificationProviderProps> = ({ children }) => {
  const location = useLocation();
  const { lastMessage } = useWebSocket();
  const [currentPage, setCurrentPageState] = useState<CurrentPageInfo>({ page: '/' });
  const [outOfDateState, setOutOfDateState] = useState<OutOfDateState>({ isOutOfDate: false });
  const [onDataRefresh, setOnDataRefresh] = useState<((data: unknown) => void) | undefined>();

  // Update current page based on route changes
  useEffect(() => {
    const path = location.pathname;
    let pageInfo: CurrentPageInfo = { page: path };

    // Parse route to determine entity type and ID
    if (path.startsWith('/space/')) {
      const spaceId = path.split('/')[2];
      pageInfo = {
        page: path,
        entityType: 'space',
        entityId: spaceId,
        isEditing: currentPage.isEditing // Preserve editing state
      };
    } else if (path.startsWith('/user/')) {
      const userId = path.split('/')[2];
      pageInfo = {
        page: path,
        entityType: 'user',
        entityId: userId,
        isEditing: currentPage.isEditing // Preserve editing state
      };
    } else if (path === '/spaces') {
      pageInfo = { page: path, entityType: undefined };
    } else if (path === '/users') {
      pageInfo = { page: path, entityType: undefined };
    }

    setCurrentPageState(pageInfo);
    
    // Clear out-of-date state when navigating to a new page
    if (path !== currentPage.page) {
      setOutOfDateState({ isOutOfDate: false });
    }
  }, [location.pathname]);

  // Handle WebSocket change messages
  useEffect(() => {
    if (lastMessage && lastMessage.type === 'change') {
      const changeMsg = lastMessage as ChangeMessage;
      handleChangeNotification(changeMsg);
    }
  }, [lastMessage]);

  const handleChangeNotification = async (changeMsg: ChangeMessage) => {
    const shouldRefresh = isChangeRelevant(changeMsg, currentPage);
    
    if (shouldRefresh) {
      if (currentPage.isEditing) {
        // If currently editing, mark as out of date instead of auto-refreshing
        setOutOfDateState({
          isOutOfDate: true,
          affectedEntity: changeMsg.group === 'user' || changeMsg.group === 'space' ? {
            type: changeMsg.group,
            id: changeMsg.userId || changeMsg.spaceId || ''
          } : undefined
        });
      } else {
        // Auto-refresh data if not editing
        try {
          await refreshCurrentData();
        } catch {
          // Refresh failed silently
        }
      }
    }
  };

  const isChangeRelevant = (changeMsg: ChangeMessage, page: CurrentPageInfo): boolean => {
    // Check if the change message is relevant to the current page
    switch (changeMsg.group) {
      case 'users':
        // Relevant if viewing users list
        return page.page === '/users';
        
      case 'spaces':
        // Relevant if viewing spaces list
        return page.page === '/spaces';
        
      case 'user':
        // Relevant if viewing specific user and IDs match
        return page.entityType === 'user' && 
               page.entityId === changeMsg.userId;
        
      case 'space':
        // Relevant if viewing specific space and IDs match
        return page.entityType === 'space' && 
               page.entityId === changeMsg.spaceId;
        
      default:
        return false;
    }
  };

  const refreshCurrentData = async (): Promise<void> => {
    if (!currentPage.entityType || !currentPage.entityId) {
      // For list pages, just trigger a refresh callback if available
      if (onDataRefresh) {
        onDataRefresh(null);
      }
      return;
    }

    let data;
    
    if (currentPage.entityType === 'space') {
      data = await apiService.getSpaceInfo(currentPage.entityId);
    } else if (currentPage.entityType === 'user') {
      data = await apiService.getUser(currentPage.entityId);
    }
    
    if (data && onDataRefresh) {
      onDataRefresh(data);
    }
  };

  const setCurrentPage = (page: CurrentPageInfo) => {
    setCurrentPageState(page);
    // Clear out-of-date state when manually setting page
    setOutOfDateState({ isOutOfDate: false });
  };

  const setEditingState = (isEditing: boolean) => {
    setCurrentPageState(prev => ({
      ...prev,
      isEditing
    }));
    
    // Clear out-of-date state when starting to edit
    if (isEditing) {
      setOutOfDateState({ isOutOfDate: false });
    }
  };

  const dismissOutOfDate = () => {
    setOutOfDateState({ isOutOfDate: false });
  };

  const setOnDataRefreshCallback = (callback: (data: unknown) => void) => {
    setOnDataRefresh(() => callback);
  };

  return (
    <ChangeNotificationContext.Provider
      value={{
        currentPage,
        outOfDateState,
        setCurrentPage,
        setEditingState,
        refreshCurrentData,
        dismissOutOfDate,
        onDataRefresh,
        setOnDataRefresh: setOnDataRefreshCallback,
      }}
    >
      {children}
    </ChangeNotificationContext.Provider>
  );
};
