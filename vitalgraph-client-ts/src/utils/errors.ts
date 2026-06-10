/**
 * Base exception for VitalGraph client errors.
 */
export class VitalGraphClientError extends Error {
  public statusCode?: number;

  constructor(message: string, statusCode?: number) {
    super(message);
    this.name = 'VitalGraphClientError';
    this.statusCode = statusCode;
  }
}
