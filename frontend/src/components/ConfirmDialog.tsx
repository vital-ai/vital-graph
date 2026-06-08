import React from 'react';
import { Button } from 'flowbite-react';
import { HiTrash, HiExclamation } from 'react-icons/hi';

type ConfirmVariant = 'danger' | 'warning';

interface ConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  description?: React.ReactNode;
  detail?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: ConfirmVariant;
  icon?: React.ReactNode;
}

const variantConfig: Record<ConfirmVariant, { icon: React.ReactNode; buttonColor: string }> = {
  danger: {
    icon: <HiTrash className="h-12 w-12 text-red-400" />,
    buttonColor: 'failure',
  },
  warning: {
    icon: <HiExclamation className="h-12 w-12 text-yellow-400" />,
    buttonColor: 'warning',
  },
};

const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  onConfirm,
  onCancel,
  title,
  description,
  detail,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'danger',
  icon,
}) => {
  if (!open) return null;

  const config = variantConfig[variant];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg max-w-md w-full mx-4 p-6">
        <div className="flex justify-center mb-4">
          {icon || config.icon}
        </div>
        <h3 id="confirm-dialog-title" className="text-lg font-semibold text-gray-900 dark:text-white text-center mb-2">
          {title}
        </h3>
        {description && (
          <p className="text-sm text-gray-500 dark:text-gray-400 text-center mb-1">
            {description}
          </p>
        )}
        {detail && (
          <div className="bg-gray-50 dark:bg-gray-700 rounded p-3 my-3 text-xs font-mono break-all space-y-1">
            {detail}
          </div>
        )}
        <p className="text-xs text-red-500 text-center mb-4">This cannot be undone.</p>
        <div className="flex gap-2">
          <Button color={config.buttonColor as 'failure' | 'warning'} onClick={onConfirm} className="flex-1">
            {confirmLabel}
          </Button>
          <Button color="gray" onClick={onCancel} className="flex-1">
            {cancelLabel}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDialog;
