import { useState, useCallback } from 'react';

type ValidationRule = {
  required?: boolean | string;
  minLength?: [number, string];
  maxLength?: [number, string];
  pattern?: [RegExp, string];
  custom?: (value: string) => string | undefined;
};

type ValidationRules<T extends string> = Record<T, ValidationRule>;

/**
 * Lightweight form validation hook.
 * Returns field errors, a validate function, and helpers to clear errors on change.
 */
export function useFormValidation<T extends string>(rules: ValidationRules<T>) {
  const [errors, setErrors] = useState<Partial<Record<T, string>>>({});

  const validateField = useCallback((field: T, value: string): string | undefined => {
    const rule = rules[field];
    if (!rule) return undefined;

    if (rule.required) {
      if (!value.trim()) {
        return typeof rule.required === 'string' ? rule.required : `This field is required`;
      }
    }
    if (rule.minLength && value.length < rule.minLength[0]) {
      return rule.minLength[1];
    }
    if (rule.maxLength && value.length > rule.maxLength[0]) {
      return rule.maxLength[1];
    }
    if (rule.pattern && !rule.pattern[0].test(value)) {
      return rule.pattern[1];
    }
    if (rule.custom) {
      return rule.custom(value);
    }
    return undefined;
  }, [rules]);

  const validate = useCallback((values: Record<T, string>): boolean => {
    const newErrors: Partial<Record<T, string>> = {};
    let valid = true;

    for (const field of Object.keys(rules) as T[]) {
      const error = validateField(field, values[field] || '');
      if (error) {
        newErrors[field] = error;
        valid = false;
      }
    }

    setErrors(newErrors);
    return valid;
  }, [rules, validateField]);

  const clearError = useCallback((field: T) => {
    setErrors((prev) => {
      if (!prev[field]) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });
  }, []);

  const clearAll = useCallback(() => setErrors({}), []);

  return { errors, validate, validateField, clearError, clearAll, setErrors };
}
