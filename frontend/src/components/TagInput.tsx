import React, { useId } from 'react';
import { TextInput } from 'flowbite-react';

interface TagInputProps {
  value: string;
  onChange: (value: string) => void;
  /** Existing values to offer as suggestions */
  suggestions: string[];
  placeholder?: string;
  id?: string;
  'data-testid'?: string;
}

/**
 * Free-text field that suggests values already in use.
 *
 * Identifier namespaces and alias types have no lookup table and no FK — the
 * vocabulary is owned by whatever writes to the registry, so this must accept
 * new values while still steering towards the existing ones. A <datalist> gives
 * exactly that: suggestions without constraint.
 */
const TagInput: React.FC<TagInputProps> = ({
  value, onChange, suggestions, placeholder, id, 'data-testid': testId,
}) => {
  const listId = `${useId()}-tags`;
  return (
    <>
      <TextInput
        id={id}
        data-testid={testId}
        list={listId}
        autoComplete="off"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <datalist id={listId}>
        {suggestions.map((s) => <option key={s} value={s} />)}
      </datalist>
    </>
  );
};

export default TagInput;
