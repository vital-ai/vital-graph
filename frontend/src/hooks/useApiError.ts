import { useState, useCallback } from 'react';

interface ApiErrorState {
  error: string | null;
  setError: (msg: string | null) => void;
  clearError: () => void;
  handleError: (err: unknown, fallbackMessage?: string) => void;
}

/**
 * Hook for consistent API error handling across pages.
 * Extracts error messages from various error shapes (Error, AxiosError, string).
 */
export function useApiError(): ApiErrorState {
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => setError(null), []);

  const handleError = useCallback((err: unknown, fallbackMessage = 'An unexpected error occurred') => {
    if (err instanceof Error) {
      setError(err.message);
    } else if (typeof err === 'string') {
      setError(err);
    } else if (err && typeof err === 'object' && 'response' in err) {
      // Axios-style error
      const axiosErr = err as { response?: { data?: { detail?: string; message?: string }; status?: number } };
      const detail = axiosErr.response?.data?.detail || axiosErr.response?.data?.message;
      setError(detail || `Request failed with status ${axiosErr.response?.status}`);
    } else {
      setError(fallbackMessage);
    }
  }, []);

  return { error, setError, clearError, handleError };
}

export default useApiError;
