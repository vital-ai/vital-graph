import React from 'react';
import { Alert, Button } from 'flowbite-react';
import { HiExclamation } from 'react-icons/hi';

interface ErrorDisplayProps {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

const ErrorDisplay: React.FC<ErrorDisplayProps> = ({ message, onRetry, onDismiss }) => {
  return (
    <Alert
      color="failure"
      icon={HiExclamation}
      onDismiss={onDismiss}
      className="mb-4"
    >
      <div className="flex items-center justify-between w-full">
        <span>{message}</span>
        {onRetry && (
          <Button size="xs" color="failure" onClick={onRetry} className="ml-4">
            Retry
          </Button>
        )}
      </div>
    </Alert>
  );
};

export default ErrorDisplay;
