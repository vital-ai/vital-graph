import React, { useState, useRef, useEffect } from 'react';

interface ExpandableTextProps {
  text: string;
  maxLines?: number;
  className?: string;
}

/**
 * Displays text with a configurable line clamp.
 * Shows "Show more" / "Show less" toggle when content overflows.
 */
const ExpandableText: React.FC<ExpandableTextProps> = ({
  text,
  maxLines = 3,
  className = '',
}) => {
  const [expanded, setExpanded] = useState(false);
  const [isClamped, setIsClamped] = useState(false);
  const textRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = textRef.current;
    if (el) {
      setIsClamped(el.scrollHeight > el.clientHeight);
    }
  }, [text, maxLines]);

  return (
    <div className={className}>
      <div
        ref={textRef}
        className={`text-sm text-gray-900 dark:text-white whitespace-pre-wrap break-words ${
          !expanded ? 'overflow-hidden' : ''
        }`}
        style={!expanded ? { display: '-webkit-box', WebkitLineClamp: maxLines, WebkitBoxOrient: 'vertical' } : undefined}
      >
        {text}
      </div>
      {isClamped && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-blue-600 dark:text-blue-400 hover:underline mt-1 font-medium"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
};

export default ExpandableText;
