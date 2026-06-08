import React, { useState, useCallback } from 'react';
import { HiClipboardCopy, HiCheck } from 'react-icons/hi';

interface CopyButtonProps {
  text: string;
  className?: string;
  size?: 'sm' | 'md';
}

/**
 * A small icon button that copies text to clipboard.
 * Shows a checkmark briefly after copying.
 */
const CopyButton: React.FC<CopyButtonProps> = ({ text, className = '', size = 'sm' }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement('textarea');
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }, [text]);

  const iconSize = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4';
  const padding = size === 'sm' ? 'p-1' : 'p-1.5';

  return (
    <button
      onClick={handleCopy}
      aria-label={copied ? 'Copied' : 'Copy to clipboard'}
      title={copied ? 'Copied!' : 'Copy to clipboard'}
      className={`${padding} rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors inline-flex items-center ${className}`}
    >
      {copied ? (
        <HiCheck className={`${iconSize} text-green-500`} />
      ) : (
        <HiClipboardCopy className={iconSize} />
      )}
    </button>
  );
};

export default CopyButton;
