import React from 'react';
import { Label } from 'flowbite-react';

interface FormFieldProps {
  label: string;
  htmlFor?: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}

/**
 * Reusable form field wrapper with label, error message, and optional hint.
 * Highlights the field border red when an error is present.
 */
const FormField: React.FC<FormFieldProps> = ({
  label,
  htmlFor,
  error,
  hint,
  required,
  children,
}) => {
  return (
    <div className="space-y-1">
      <Label htmlFor={htmlFor} className="flex items-center gap-1">
        {label}
        {required && <span className="text-red-500">*</span>}
      </Label>
      <div className={error ? '[&_input]:border-red-500 [&_input]:dark:border-red-500 [&_select]:border-red-500' : ''}>
        {children}
      </div>
      {error && (
        <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">{error}</p>
      )}
      {!error && hint && (
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{hint}</p>
      )}
    </div>
  );
};

export default FormField;
