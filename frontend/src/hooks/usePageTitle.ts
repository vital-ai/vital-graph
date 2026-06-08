import { useEffect } from 'react';

const APP_NAME = 'VitalGraph';

/**
 * Sets the browser tab title. Resets to app name on unmount.
 * @param title - Page-specific title (will be appended with app name)
 */
export function usePageTitle(title?: string) {
  useEffect(() => {
    document.title = title ? `${title} | ${APP_NAME}` : APP_NAME;
    return () => {
      document.title = APP_NAME;
    };
  }, [title]);
}
