import React, { useState, useEffect, useCallback } from 'react';
import { Spinner, Button, Textarea } from 'flowbite-react';
import { HiPencil, HiCheck, HiX, HiTrash } from 'react-icons/hi';
import { apiService } from '../services/ApiService';

// ── Simple markdown-to-HTML converter (no external deps) ──────────────
// Handles headings, bold, italic, code blocks, inline code, lists, links, paragraphs.

function markdownToHtml(md: string): string {
  let html = md
    // Fenced code blocks
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="bg-gray-100 dark:bg-gray-800 rounded p-3 text-sm overflow-x-auto my-2"><code>$2</code></pre>')
    // Headings
    .replace(/^#### (.+)$/gm, '<h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-3 mb-1">$1</h4>')
    .replace(/^### (.+)$/gm, '<h3 class="text-base font-semibold text-gray-700 dark:text-gray-300 mt-4 mb-1">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="text-lg font-semibold text-gray-700 dark:text-gray-200 mt-4 mb-2">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="text-xl font-bold text-gray-800 dark:text-gray-100 mt-4 mb-2">$1</h1>')
    // Bold + italic
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code class="bg-gray-100 dark:bg-gray-800 px-1 rounded text-sm">$1</code>')
    // Unordered list items
    .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc text-sm text-gray-600 dark:text-gray-400">$1</li>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-blue-500 hover:underline" target="_blank" rel="noopener">$1</a>')
    // Paragraphs (double newline)
    .replace(/\n\n/g, '</p><p class="text-sm text-gray-600 dark:text-gray-400 mb-2">')
    // Single newlines inside paragraphs
    .replace(/\n/g, '<br/>');

  // Wrap list items in <ul>
  html = html.replace(/((?:<li[^>]*>.*?<\/li>\s*)+)/g, '<ul class="my-1">$1</ul>');

  return `<p class="text-sm text-gray-600 dark:text-gray-400 mb-2">${html}</p>`;
}

// ── Component ─────────────────────────────────────────────────────────

interface TypeDocumentationPanelProps {
  spaceId: string;
  graphId?: string; // deprecated, ignored — backend derives graph from space
  typeUri: string;
}

const TypeDocumentationPanel: React.FC<TypeDocumentationPanelProps> = ({
  spaceId, typeUri,
}) => {
  const [content, setContent] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDocumentation = useCallback(async () => {
    if (!spaceId || !typeUri) return;
    try {
      setLoading(true);
      setError(null);
      const resp = await apiService.getKGTypeDocumentation(spaceId, typeUri);
      setContent(resp.content || null);
    } catch (e: unknown) {
      // 404 means no documentation exists — that's fine
      if (e instanceof Error && e.message.includes('404')) {
        setContent(null);
      } else {
        setError(e instanceof Error ? e.message : 'Failed to load documentation');
      }
    } finally {
      setLoading(false);
    }
  }, [spaceId, typeUri]);

  useEffect(() => { fetchDocumentation(); }, [fetchDocumentation]);

  const handleEdit = () => {
    setEditContent(content || '');
    setEditing(true);
  };

  const handleCancel = () => {
    setEditing(false);
    setEditContent('');
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      await apiService.updateKGTypeDocumentation(spaceId, typeUri, editContent);
      setContent(editContent);
      setEditing(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save documentation');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm('Delete documentation for this type?')) return;
    try {
      setSaving(true);
      await apiService.deleteKGTypeDocumentation(spaceId, typeUri);
      setContent(null);
      setEditing(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to delete documentation');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
        <div className="flex items-center justify-center py-4">
          <Spinner size="md" />
          <span className="ml-2 text-sm text-gray-500">Loading documentation...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          Documentation
        </h3>
        <div className="flex items-center gap-2">
          {!editing && (
            <Button size="xs" color="light" onClick={handleEdit}>
              <HiPencil className="w-3.5 h-3.5 mr-1" />
              {content ? 'Edit' : 'Add'}
            </Button>
          )}
          {!editing && content && (
            <Button size="xs" color="light" onClick={handleDelete} disabled={saving}>
              <HiTrash className="w-3.5 h-3.5 mr-1" />
              Delete
            </Button>
          )}
        </div>
      </div>

      {error && (
        <p className="text-sm text-red-500 mb-2">{error}</p>
      )}

      {editing ? (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-4">
            {/* Editor */}
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                Markdown
              </label>
              <Textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                rows={16}
                className="font-mono text-sm"
                placeholder="# Documentation&#10;&#10;Write markdown here..."
              />
            </div>
            {/* Preview */}
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                Preview
              </label>
              <div
                className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 min-h-[24rem] overflow-y-auto
                  prose prose-sm dark:prose-invert max-w-none"
                dangerouslySetInnerHTML={{ __html: markdownToHtml(editContent) }}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button size="xs" color="blue" onClick={handleSave} disabled={saving}>
              <HiCheck className="w-3.5 h-3.5 mr-1" />
              {saving ? 'Saving...' : 'Save'}
            </Button>
            <Button size="xs" color="light" onClick={handleCancel} disabled={saving}>
              <HiX className="w-3.5 h-3.5 mr-1" />
              Cancel
            </Button>
          </div>
        </div>
      ) : content ? (
        <div
          className="prose prose-sm dark:prose-invert max-w-none"
          dangerouslySetInnerHTML={{ __html: markdownToHtml(content) }}
        />
      ) : (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">
          No documentation. Click "Add" to write markdown documentation for this type.
        </p>
      )}
    </div>
  );
};

export default TypeDocumentationPanel;
