import React from 'react';
import { HiCheck, HiX, HiExclamation, HiInformationCircle } from 'react-icons/hi';
import { useToast } from '../contexts/ToastContext';

const iconMap = {
  success: <HiCheck className="w-5 h-5" />,
  error: <HiX className="w-5 h-5" />,
  warning: <HiExclamation className="w-5 h-5" />,
  info: <HiInformationCircle className="w-5 h-5" />,
};

const colorMap = {
  success: 'bg-green-100 text-green-500 dark:bg-green-800 dark:text-green-200',
  error: 'bg-red-100 text-red-500 dark:bg-red-800 dark:text-red-200',
  warning: 'bg-yellow-100 text-yellow-500 dark:bg-yellow-800 dark:text-yellow-200',
  info: 'bg-blue-100 text-blue-500 dark:bg-blue-800 dark:text-blue-200',
};

const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useToast();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-200 flex flex-col gap-2 max-w-sm">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="flex items-center gap-3 p-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg animate-in slide-in-from-right"
          role="alert"
        >
          <div className={`inline-flex items-center justify-center shrink-0 w-8 h-8 rounded-lg ${colorMap[toast.type]}`}>
            {iconMap[toast.type]}
          </div>
          <div className="text-sm font-normal text-gray-900 dark:text-white flex-1">
            {toast.message}
          </div>
          <button
            onClick={() => removeToast(toast.id)}
            aria-label="Dismiss notification"
            className="ml-2 inline-flex items-center justify-center w-6 h-6 text-gray-400 hover:text-gray-900 dark:hover:text-white rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
          >
            <HiX className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  );
};

export default ToastContainer;
