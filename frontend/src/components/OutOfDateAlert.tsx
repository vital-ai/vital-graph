import { Alert, Button } from 'flowbite-react';
import { HiInformationCircle, HiRefresh, HiX } from 'react-icons/hi';

interface OutOfDateAlertProps {
  isVisible: boolean;
  entityType?: 'user' | 'space';
  entityId?: string;
  onRefresh: () => Promise<void>;
  onCancel: () => void;
  onDismiss?: () => void;
  isRefreshing?: boolean;
}

export default function OutOfDateAlert({
  isVisible,
  entityType,
  entityId,
  onRefresh,
  onCancel,
  onDismiss,
  isRefreshing = false
}: OutOfDateAlertProps) {
  if (!isVisible) {
    return null;
  }

  const handleRefresh = async () => {
    try {
      await onRefresh();
    } catch (error) {
      console.error('Failed to refresh:', error);
    }
  };

  const getEntityDescription = () => {
    if (entityType && entityId) {
      return `${entityType} (ID: ${entityId})`;
    }
    return 'this item';
  };

  return (
    <Alert
      color="warning"
      icon={HiInformationCircle}
      className="mb-4"
      additionalContent={
        <div className="mt-4 flex flex-col sm:flex-row gap-2">
          <Button
            size="sm"
            color="warning"
            onClick={handleRefresh}
            disabled={isRefreshing}
          >
            <HiRefresh className="mr-2 h-4 w-4" />
            {isRefreshing ? 'Refreshing...' : 'Refresh Data'}
          </Button>
          <Button
            size="sm"
            color="gray"
            onClick={onCancel}
            disabled={isRefreshing}
          >
            <HiX className="mr-2 h-4 w-4" />
            Cancel Editing
          </Button>
          {onDismiss && (
            <Button
              size="sm"
              color="light"
              onClick={onDismiss}
              disabled={isRefreshing}
            >
              Dismiss
            </Button>
          )}
        </div>
      }
    >
      <div className="font-medium text-yellow-800 dark:text-yellow-300">
        Data Out of Date
      </div>
      <div className="text-sm text-yellow-700 dark:text-yellow-400">
        The {getEntityDescription()} you are editing has been modified by another user or process. 
        Your changes cannot be saved until you refresh the data or cancel editing.
      </div>
    </Alert>
  );
}
