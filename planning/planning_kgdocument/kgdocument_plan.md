# KGDocument Implementation Plan

## 1. Overview

This document covers the implementation of **KGDocument** support in VitalGraph, including:

1. **UI Screen** — A dedicated KG Documents page in the frontend below KG Relations
2. **Vector Indexing** — Vectorization of KGDocument objects (already partially supported in mapping config)
3. **Document Segmentation** — Splitting documents into N indexed segments ("chunks") with parent-child relationships
4. **Similarity Search** — Leveraging existing SPARQL `vg:vectorSimilarity` to retrieve matching text chunks

---

## 2. Domain Model (from haley-ai-kg ontology)

### 2.1 KGDocument Class

- **Class URI**: `http://vital.ai/ontology/haley-ai-kg#KGDocument`
- **Extends**: `KGNode` → `VITAL_Node`

**KGDocument-specific properties:**

| Property URI | TS Name | Type | Purpose |
|---|---|---|---|
| `haley:hasKGDocumentContent` | `kGDocumentContent` | string | Full text content |
| `haley:hasKGDocumentExtractedContent` | `kGDocumentExtractedContent` | string | Extracted/parsed content |
| `haley:hasKGDocumentHTMLContent` | `kGDocumentHTMLContent` | string | HTML representation |
| `haley:hasKGDocumentHeadline` | `kGDocumentHeadline` | string | Document title/headline |
| `haley:hasKGDocumentDescription` | `kGDocumentDescription` | string | Description/abstract |
| `haley:hasKGDocumentSummary` | `kGDocumentSummary` | string | AI-generated summary |
| `haley:hasKGDocumentURL` | `kGDocumentURL` | string | Source URL |
| `haley:hasKGDocumentType` | `kGDocumentType` | URI | Reference to KGDocumentType |
| `haley:hasKGDocumentPublicationDateTime` | `kGDocumentPublicationDateTime` | datetime | Publication date |
| `haley:hasKGDocumentRetrievalDateTime` | `kGDocumentRetrievalDateTime` | datetime | When retrieved/ingested |
| `haley:hasKGDocumentTokenLength` | `kGDocumentTokenLength` | integer | Total token count |
| `haley:hasKGDocumentSegmentIndex` | `kGDocumentSegmentIndex` | integer | Segment ordinal (0 = parent) |
| `haley:hasKGDocumentSegmentMethodURI` | `kGDocumentSegmentMethodURI` | URI | Reference to segmentation method |
| `haley:hasKGDocumentSegmentTypeURI` | `kGDocumentSegmentTypeURI` | URI | Reference to segment type |
| `haley:hasKGDocumentSegmentTokenLength` | `kGDocumentSegmentTokenLength` | integer | Segment token count |
| `haley:hasKGDocumentStartTokenIndex` | `kGDocumentStartTokenIndex` | integer | Start position (token offset) |
| `haley:hasKGDocumentEndTokenIndex` | `kGDocumentEndTokenIndex` | integer | End position (token offset) |
| `haley:hasKGContentType` | `kGContentType` | string | MIME type or content classification |
| `haley:hasKGEncodedByteData` | `kGEncodedByteData` | string | Base64-encoded binary data |
| `haley:hasPrimaryLanguageType` | `primaryLanguageType` | URI | Language classification |
| `haley:hasTopCategoryURIs` | `topCategoryURIs` | string | Category classifications |

**Inherited from KGNode:**
- `hasKGraphDescription` — canonical vectorization text
- `hasKGIdentifier` — unique identifier
- `hasKGIndexDateTime` — when last indexed
- `hasKGIndexStatusURI` — indexing status

### 2.2 Edge_hasKGDocumentSegment

- **Class URI**: `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGDocumentSegment`
- **Extends**: `Edge_hasKGEdge` → `VITAL_PeerEdge`
- **Source**: Parent KGDocument URI
- **Destination**: Segment KGDocument URI
- **Purpose**: Links a parent document to its N segment documents

### 2.3 Related Edge Classes

| Edge Class | Purpose |
|---|---|
| `Edge_hasKGDocument` | Links an entity/node to a KGDocument |
| `Edge_hasKGDocumentFileNode` | Links a KGDocument to its source FileNode |
| `Edge_hasInteractionKGDocument` | Links an interaction to a KGDocument |

### 2.4 Supporting Types

| Class | Purpose |
|---|---|
| `KGDocumentType` | Type classification for documents (extends KGType) |
| `KGDocumentSegmentMethod` | Enum/definition of segmentation strategy (extends VITAL_Node) |
| `KGDocumentSegmentType` | Enum/definition of segment types (extends VITAL_Node) |

---

## 3. UI Implementation

### 3.1 Navigation

Add **KG Documents** to the sidebar in `Layout.tsx`, positioned between KG Relations and KG Types:

```
Knowledge Graph
├── KG Entities
├── KG Frames
├── KG Relations
├── KG Documents   ← NEW
├── KG Types
├── KG Query Builder
└── Files
```

### 3.2 KG Documents Page (`KGDocuments.tsx`)

**List View:**
- Table displaying KGDocument objects in the selected space/graph
- Columns: Name, Headline, Content Type, Document Type, Publication Date, Segment Count, Token Length
- Filters: Document Type, search by headline/content
- **Segment visibility toggle**: Hide segments by default (show only originals); toggle to reveal segments with visual indicator (e.g., indented, badge, or icon)
- Pagination with configurable page size
- Visual indicators distinguishing originals, parent copies, and segments

**Detail View:**
- Full document properties display
- Document content viewer (text, HTML, or extracted content)
- Segment list: show child segments linked via `Edge_hasKGDocumentSegment`
- Segment navigation: click a segment to view its content
- Parent link: if viewing a segment, link back to parent document
- Metadata panel: token lengths, dates, type, language, URL

**CRUD Operations:**
- Create: Upload/input document content
- Update: Edit metadata and content
- Delete: Remove document and optionally its segments

### 3.3 Integration with Object Detail Renderer

Add KGDocument-specific rendering in `ObjectDetailRenderer.tsx` to display document content, segment metadata, and parent/child relationships when viewing individual objects.

---

## 4. Vector Indexing

### 4.1 Current State

KGDocument is **already recognized** as a vectorizable class in the vector mapping system:
- `mapping_type = 'kgdocument'` is listed in `CreateMappingRequest`, `ReindexRequest`, and vector mapping docs
- Default vectorization property: `hasKGraphDescription`
- Type reference property: `hasKGDocumentType`
- The `vector_populator.py` pipeline already handles arbitrary `mapping_type` values

### 4.2 Required Work

1. **Ensure mapping creation for kgdocument**: When a space is initialized with vector support, create a default class-level mapping row:
   ```sql
   INSERT INTO {space}_vector_mapping (mapping_type, type_uri, index_name, enabled, source_type)
   VALUES ('kgdocument', NULL, 'entity_default', true, 'default');
   ```

2. **Document-specific source_type**: Add a new `source_type = 'document_content'` that uses `hasKGDocumentContent` (or `hasKGDocumentExtractedContent`) instead of `hasKGraphDescription` for the search text. This provides full-text vectorization of the actual document body rather than just the description.

3. **Auto-sync on CRUD**: When a KGDocument is created/updated, trigger incremental vector population (same pattern as KGEntity auto-sync).

---

## 5. Document Segmentation Strategy

### 5.1 Architecture Overview — Three-Tier Model

The segmentation architecture uses three tiers to preserve the original document and support multiple independent segmentations:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ORIGINAL KGDocument (never modified by segmentation)                │
│  URI: urn:doc:abc123                                                 │
│  kGDocumentContent: "# Introduction\n..."                            │
│  kGDocumentType: urn:kgdoctype:technical_article                     │
│  kGDocumentSegmentTypeURI: (not set — indicates not segmented)       │
│  kGDocumentTokenLength: 5000                                         │
└──────────────┬───────────────────────────────────────────────────────┘
               │ Edge_hasKGDocumentSegment (original → parent copy)
               │
┌──────────────▼──────────────────────────────────────────────────────┐
│  PARENT COPY KGDocument (marks a specific segmentation)              │
│  URI: urn:doc:abc123_md512                                           │
│  kGDocumentContent: (NOT full content — only summary/vectorizable text) │
│  kGDocumentType: urn:kgdoctype:document_segment                      │
│  kGDocumentSegmentTypeURI: urn:segtype:segmentation_parent           │
│  kGDocumentSegmentMethodURI: urn:segmethod:markdown_heading_split    │
│  kGDocumentSegmentIndex: 0 (indicates parent role)                   │
│  kGIndexDateTime: 2026-06-09T12:00:00Z (when segmentation occurred)  │
└──────────────┬──────────────────────────────────────────────────────┘
               │ Edge_hasKGDocumentSegment (parent copy → segments)
               ├──────────────────────────────────────────┐
               │                                          │
┌──────────────▼──────────────┐    ┌──────────────────────▼──────┐
│  Segment KGDocument (1)      │    │  Segment KGDocument (N)      │
│  URI: urn:doc:abc123_md512_1 │    │  URI: urn:doc:abc123_md512_N │
│  kGDocumentSegmentIndex: 1   │    │  kGDocumentSegmentIndex: N   │
│  kGDocumentSegmentTypeURI:   │    │  kGDocumentSegmentTypeURI:   │
│    urn:segtype:markdown_sec  │    │    urn:segtype:markdown_sec  │
│  kGDocumentSegmentMethodURI: │    │  kGDocumentSegmentMethodURI: │
│    urn:segmethod:md_heading  │    │    urn:segmethod:md_heading  │
│  kGDocumentType:             │    │  kGDocumentType:             │
│    urn:kgdoctype:doc_segment │    │    urn:kgdoctype:doc_segment │
│  kGDocumentContent: "..."    │    │  kGDocumentContent: "..."    │
│  kGDocumentSegmentTokenLen:  │    │  kGDocumentSegmentTokenLen:  │
│    500                       │    │    450                       │
│  kGDocumentStartTokenIndex:  │    │  kGDocumentStartTokenIndex:  │
│    0                         │    │    4200                      │
│  kGDocumentEndTokenIndex:    │    │  kGDocumentEndTokenIndex:    │
│    500                       │    │    4650                      │
└──────────────────────────────┘    └──────────────────────────────┘
```

**Key design benefits of the three-tier model:**

1. **Original document is never modified** — segmentation is a non-destructive operation; the original KGDocument retains all its properties unchanged
2. **Multiple independent segmentations** — the same original can have multiple parent copies, each with a different method (e.g., markdown-512 and fixed-1024):
   ```
   Original → Parent Copy A (markdown, 512 tokens) → N segments
            → Parent Copy B (fixed window, 1024 tokens) → M segments
   ```
3. **Timestamped segmentation tracking** — `kGIndexDateTime` (or `kGGraphAssertionDateTime`) on the parent copy records when segmentation was performed, enabling re-segmentation decisions
4. **Clean queryability** — filter by `kGDocumentSegmentTypeURI = urn:segtype:segmentation_parent` to find all segmented versions; absence of this property on a document means it has never been segmented
5. **Easy cleanup** — to remove a segmentation, delete the parent copy and its segment children; original document remains intact

**Using `hasKGDocumentSegmentTypeURI` on the parent copy:**
- Value `urn:segtype:segmentation_parent` marks a document as the "parent" of a segmentation run
- This distinguishes it from both the original (no segment type set) and the child segments (which have segment types like `urn:segtype:markdown_section`)
- Queries can filter: `FILTER(?segTypeURI = urn:segtype:segmentation_parent)` to find all parent copies

### 5.2 Storage Decision: Full RDF Quad Store (Option A)

**Decision**: Parent copies and segments are stored as full KGDocument objects in the main RDF quad store, with the vector index table holding only embeddings and search_text (same as all other KG objects).

**Rationale:**
- `vg:vectorSimilarity` SPARQL queries require subjects to exist in the quad store for JOIN binding
- The ontology defines `KGDocument` and `Edge_hasKGDocumentSegment` as first-class graph objects — use them as designed
- Standard graph object retrieval works without custom plumbing (segment + edge + parent in one fetch)
- The existing vector populator indexes subjects that already exist in the quad store — no pipeline changes needed
- Segments are filtered from general document listings via `kGDocumentType = urn:kgdoctype:document_segment`
- Enables future attachment of frames, relations, or annotations to individual segments

**Storage cost**: ~15-20 triples per segment. A 5000-token document split into 10 segments ≈ 200 quads — negligible.

### 5.3 Grouping URIs & Entity Linkage

**Same RDF graph (context)**: Segments are stored in the same named graph as the original document. No dedicated "segments" graph — this keeps querying simple and avoids cross-graph joins.

**Grouping via `kGGraphURI`**: All objects in a document segmentation cluster (parent copy, segments, edges) share the same `kGGraphURI` pointing to the original document's entity graph. This enables:
- Bulk retrieval of an entire segmentation cluster via grouping URI
- Consistent membership in the same entity graph as the original document
- Standard cleanup patterns (delete all objects with a given `kGGraphURI`)

```
Original KGDocument:      kGGraphURI = urn:entitygraph:abc123
Parent Copy KGDocument:   kGGraphURI = urn:entitygraph:abc123
Segment 1 KGDocument:     kGGraphURI = urn:entitygraph:abc123
Segment N KGDocument:     kGGraphURI = urn:entitygraph:abc123
Edge (orig→parent):       kGGraphURI = urn:entitygraph:abc123
Edge (parent→seg 1):      kGGraphURI = urn:entitygraph:abc123
```

**Entity → Document linkage via `KGURISlot`**: When a KGEntity needs to reference a KGDocument, this is done through a `KGURISlot` on the entity's frame. The slot holds the document URI as its value. This avoids inventing new edge types and uses the existing frame/slot model:

```
KGEntity (e.g., "Research Paper X")
  └── KGFrame (e.g., "DocumentReferenceFrame")
        └── KGURISlot (e.g., slotType = "urn:slottype:document_reference")
              └── value = urn:doc:abc123  (the KGDocument URI)
```

This pattern means:
- Entities can point to documents via their standard frame/slot structure
- Multiple entities can reference the same document
- The document's segments are discoverable by following `Edge_hasKGDocumentSegment` from the referenced document URI
- No new edge classes needed for entity→document relationships (though `Edge_hasKGDocument` exists as an alternative if a direct edge is preferred)

### 5.4 Segmentation Metadata Properties

Three URI-typed properties on KGDocument drive segmentation metadata:

| Property | Purpose | Example Value |
|---|---|---|
| `hasKGDocumentType` | Classifies the document. Segments use a **segment-specific** document type to distinguish them from parent documents. | `urn:kgdoctype:document_segment` |
| `hasKGDocumentSegmentMethodURI` | Records **how** segmentation was performed (the algorithm/strategy). Points to a `KGDocumentSegmentMethod` instance. | `urn:segmethod:markdown_heading_split` |
| `hasKGDocumentSegmentTypeURI` | Records **what kind** of segment this is (the structural unit). Points to a `KGDocumentSegmentType` instance. | `urn:segtype:markdown_section` |

**Segment Method examples** (`KGDocumentSegmentMethod` instances):
- `urn:segmethod:markdown_heading_split` — split by markdown headings with token-max secondary split
- `urn:segmethod:fixed_token_window` — fixed token count with overlap
- `urn:segmethod:sentence_boundary` — split at sentence boundaries
- `urn:segmethod:semantic_topic` — embedding-similarity topic detection

**Segment Type examples** (`KGDocumentSegmentType` instances):
- `urn:segtype:markdown_section` — a heading-delimited markdown section
- `urn:segtype:paragraph` — a paragraph-level chunk
- `urn:segtype:sentence_group` — a group of sentences
- `urn:segtype:token_window` — a fixed-size token window
- `urn:segtype:code_block` — an extracted code block

**Parent vs Segment distinction**: The parent document has a standard `hasKGDocumentType` (e.g., `urn:kgdoctype:technical_article`). Segments carry a segment-specific document type (e.g., `urn:kgdoctype:document_segment`) so queries can easily filter parents from segments without checking `kGDocumentSegmentIndex`.

### 5.4 Segmentation Triggers

**Manual**: Segmentation can always be triggered explicitly via the `/segment` API endpoint, specifying the method and parameters.

**Automatic**: A configurable mapping of document type → segmentation config enables auto-segmentation on document insert/update. When a KGDocument is created or updated and its `kGDocumentType` matches a registered mapping, segmentation runs automatically.

**Mapping table** (`{space}_document_segmentation_config`):

| Column | Type | Description |
|---|---|---|
| `config_id` | SERIAL PK | |
| `document_type_uri` | VARCHAR(500) | KGDocumentType URI that triggers auto-segmentation |
| `segment_method_uri` | VARCHAR(500) | Segmentation method to apply |
| `max_segment_tokens` | INT | Token budget per segment |
| `min_segment_tokens` | INT | Minimum viable segment |
| `overlap_tokens` | INT | Overlap between segments |
| `enabled` | BOOLEAN | On/off switch |
| `auto_vectorize` | BOOLEAN | Trigger vectorization after segmentation |

**Example**: All documents of type `urn:kgdoctype:technical_article` are auto-segmented with markdown splitting at 512 tokens:

```sql
INSERT INTO {space}_document_segmentation_config
  (document_type_uri, segment_method_uri, max_segment_tokens, enabled, auto_vectorize)
VALUES
  ('urn:kgdoctype:technical_article', 'urn:segmethod:markdown_heading_split', 512, true, true);
```

**Re-segmentation policy**: Only documents with an active auto-segmentation config are automatically re-segmented on update. Documents segmented manually (no config mapping) are left as-is until manually re-triggered — the system does not invalidate them.

**Behavior on update** (auto-segmented documents only):
1. Delete existing parent copy + segments for that method (if any)
2. Re-run segmentation with current config
3. Re-vectorize new segments

This ensures segments always reflect the latest document content without manual intervention.

### 5.4.1 Concurrency & Multi-Method Coexistence

**Concurrency**: Only one segmentation request per document should be processed at a time. Uses the same `EntityLockManager` advisory lock pattern as KG entity updates — lock on the original document URI during segmentation:

```python
# Acquire advisory lock on original document URI before segmenting
async with lock_manager.lock(original_document_uri):
    # Delete existing parent copy + segments for this method
    # Create new parent copy + segments
    # Vectorize
```

This provides both in-process serialization (asyncio.Lock) and cross-instance coordination (PG advisory lock). If two identical requests arrive simultaneously, the second waits for the first to complete, then overwrites.

**Multi-method coexistence**: Multiple segmentation methods can coexist for the same original document. Each method has its own parent copy + segment cluster:

```
Original → Parent Copy A (markdown, 512 tokens) → N segments
         → Parent Copy B (fixed window, 1024 tokens) → M segments
```

Two requests with the **same** method overwrite each other (delete old parent copy + segments, recreate). Two requests with **different** methods coexist independently.

**Querying with multiple methods**: When a similarity search request doesn't specify a segmentation method, a default ordering determines which method's segments are searched:

1. If `segment_method_uri` is specified in the search request → filter to that method's segments only
2. If not specified → use a default method priority (configurable per space, e.g., markdown first)
3. Alternatively, search across all methods and deduplicate by original document in results

The `kGDocumentSegmentMethodURI` property on segments enables filtering in SPARQL:

```sparql
# Filter to a specific segmentation method
?segment haley:hasKGDocumentSegmentMethodURI <urn:segmethod:markdown_heading_split> .
```

### 5.5 Segmentation Methods

#### Markdown Splitting (Primary)

Splitting logic follows the same approach as LangChain's `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter`. We can either use those directly or implement equivalent logic in-house to avoid the dependency.

**Reference implementation** (LangChain-style):

```python
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# Primary split: by markdown headings
headers_to_split_on = [
    ("#", "h1"), ("##", "h2"), ("###", "h3"),
]
md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
md_sections = md_splitter.split_text(document_content)

# Secondary split: oversized sections get recursive character splitting
char_splitter = RecursiveCharacterTextSplitter(
    chunk_size=max_segment_tokens,
    chunk_overlap=overlap_tokens,
)
final_segments = char_splitter.split_documents(md_sections)
```

**In-house equivalent** (preferred if avoiding dependency):

```python
# Primary: regex-based markdown heading split
import re

def split_by_headings(text: str, levels: List[int]) -> List[dict]:
    """Split markdown text by heading levels. Returns list of {heading, content}."""
    pattern = r'^(#{1,' + str(max(levels)) + r'})\s+(.+)$'
    sections = []
    # Split at heading boundaries, preserve heading in section
    ...

def recursive_split(text: str, max_chars: int, overlap: int = 0) -> List[str]:
    """Split text recursively: paragraphs → sentences → words."""
    separators = ["\n\n", "\n", ". ", " "]
    # Try each separator in order until chunks fit within max_chars
    ...
```

The core logic is straightforward — regex heading detection + recursive splitting at natural boundaries — and avoids pulling in `langchain_text_splitters` and `langchain_community` as dependencies.

1. **Primary split**: `MarkdownHeaderTextSplitter` splits by headings (`#`, `##`, `###`)
   - Each heading-delimited section becomes a candidate segment
   - Each segment gets `kGDocumentSegmentTypeURI = urn:segtype:markdown_section`
   - Heading text is preserved in the segment content
2. **Secondary split**: `RecursiveCharacterTextSplitter` handles oversized sections
   - Splits at paragraph → sentence → word boundaries (recursive fallback)
   - Sub-splits may get `kGDocumentSegmentTypeURI = urn:segtype:paragraph`
3. **Overlap** (optional): `chunk_overlap` parameter on `RecursiveCharacterTextSplitter`

**Configuration:**
```python
@dataclass
class MarkdownSegmentConfig:
    max_segment_tokens: int = 512        # Max tokens per segment
    min_segment_tokens: int = 50         # Minimum viable segment size
    overlap_tokens: int = 0              # Token overlap between segments
    heading_levels: List[int] = [1, 2, 3]  # Which heading levels trigger splits
    preserve_heading: bool = True        # Include heading text in segment
    segment_method_uri: str = "urn:segmethod:markdown_heading_split"
    segment_document_type_uri: str = "urn:kgdoctype:document_segment"
```

#### Plain Splitter (for non-markdown content)

For documents that are not markdown (plain text, extracted content), use recursive character splitting only — no heading detection:

```python
@dataclass
class PlainSplitConfig:
    max_segment_tokens: int = 512        # Max tokens per segment
    min_segment_tokens: int = 50         # Minimum viable segment size
    overlap_tokens: int = 0              # Token overlap between segments
    segment_method_uri: str = "urn:segmethod:plain_recursive_split"
    segment_document_type_uri: str = "urn:kgdoctype:document_segment"
```

Splits recursively at natural boundaries: `\n\n` → `\n` → `. ` → ` ` (same as `RecursiveCharacterTextSplitter`). All segments get `kGDocumentSegmentTypeURI = urn:segtype:text_chunk`.

**Initial implementation**: Only these two methods:
1. **Markdown splitter** (`urn:segmethod:markdown_heading_split`) — for markdown content
2. **Plain splitter** (`urn:segmethod:plain_recursive_split`) — for everything else

**Auto-detection** (default behavior): If no method is explicitly specified, detect markdown content by checking for heading patterns (`^#{1,6}\s`) in the text. If headings are found, use the markdown splitter; otherwise fall back to the plain splitter. Explicit method selection via API/config overrides auto-detection.

#### Future Methods

- **Fixed-size**: Split by fixed token count with overlap (`urn:segmethod:fixed_token_window`)
- **Sentence-based**: Split at sentence boundaries targeting a token budget (`urn:segmethod:sentence_boundary`)
- **Semantic**: Use embedding similarity to detect topic boundaries (`urn:segmethod:semantic_topic`)
- **Custom**: User-defined split patterns (regex, delimiters)

### 5.5 Segmentation Pipeline

```python
async def segment_document(
    parent_document: KGDocument,
    method: MarkdownSegmentConfig,
    space_id: str,
    graph_id: str,
) -> Tuple[List[KGDocument], List[Edge_hasKGDocumentSegment]]:
    """
    Segment a parent KGDocument into N child segments.
    
    Returns:
        - List of segment KGDocument objects
        - List of Edge_hasKGDocumentSegment edges linking parent → segments
    """
```

**Pipeline steps:**

1. **Extract text**: Use the following priority/fallback order:
   1. `kGDocumentExtractedContent` (preferred — already parsed/cleaned)
   2. `kGDocumentHTMLContent` (strip HTML tags using BeautifulSoup or equivalent library)
   3. `kGDocumentContent` (raw text fallback)
2. **Detect format**: Identify if content is markdown, plain text, HTML
3. **Apply splitting strategy**: Split according to configured method
4. **Create segment KGDocuments**: For each chunk:
   - Generate segment URI: `{parent_uri}_seg_{index}`
   - Set `kGDocumentSegmentIndex` = ordinal (1-based)
   - Set `kGDocumentContent` = segment text
   - Set `kGDocumentSegmentTokenLength` = token count
   - Set `kGDocumentStartTokenIndex` / `kGDocumentEndTokenIndex`
   - Set `kGDocumentSegmentMethodURI` = method URI (e.g., `urn:segmethod:markdown_heading_split`)
   - Set `kGDocumentSegmentTypeURI` = segment type (e.g., `urn:segtype:markdown_section`)
   - Set `kGDocumentType` = segment document type (e.g., `urn:kgdoctype:document_segment`)
   - Copy parent metadata: `primaryLanguageType`, `kGDocumentURL`
   - Set `hasKGraphDescription` = segment text (for vectorization)
5. **Create segment edges**: For each segment, create `Edge_hasKGDocumentSegment`:
   - `edgeSource` = parent document URI
   - `edgeDestination` = segment document URI
6. **Store**: Insert all segment KGDocuments and edges into the RDF store
7. **Vectorize**: Trigger incremental vector population for parent + all segments

### 5.6 Vectorization Strategy

**Dedicated vector index**: Document segments use a separate vector index (e.g., `document_segments`) rather than sharing `entity_default`. This avoids mixing entity embeddings with chunk embeddings in similarity results and allows independent tuning (different dimensions, providers, or distance metrics if needed).

```sql
INSERT INTO {space}_vector_index
  (index_name, dimensions, distance_metric, provider, model_name, description)
VALUES ('document_segments', 384, 'cosine', 'vitalsigns',
        'paraphrase-multilingual-MiniLM-L12-v2', 'Document segment embeddings for chunk retrieval');
```

**Segments**: Each segment's `hasKGraphDescription` (= segment content) is vectorized directly. Segments are typically within the embedding model's token window.

**Parent copy**: The parent copy does **not** duplicate the full document content. It stores only the text that gets vectorized — typically a summary that fits within the embedding model's token window. This avoids doubling storage for large documents.

Strategy for parent copy `hasKGraphDescription` (vectorized text):
1. If the original has `kGDocumentSummary`, use: `"{headline}. {summary}"` (summary may have been generated by an LLM externally, but that happens outside VitalGraph)
2. Fallback: truncate content from original to fit the model's max input tokens

VitalGraph does **not** generate summaries internally — it uses whatever `hasKGDocumentSummary` is already present on the original document.

The parent copy's `kGDocumentContent` field holds only this summary text (not the full original). The full content remains solely on the original KGDocument.

This means the parent copy is retrievable via broad/topic-level queries, while segments are retrievable via specific/detail-level queries.

**Original document**: Vectorized using standard `kgdocument` mapping rules (same as any KGDocument — `hasKGraphDescription` by default). This provides a separate embedding for the original that doesn't depend on segmentation.

### 5.7 Storage in Vector Index Table

Both parent documents and segments are stored in the same vector data table (`{space}_vec_{index_name}`):

| subject_uuid | context_uuid | embedding | search_text |
|---|---|---|---|
| parent_uuid | graph_uuid | [embedding of full desc] | "Full document description..." |
| seg_1_uuid | graph_uuid | [embedding of chunk 1] | "# Introduction\nThis paper..." |
| seg_2_uuid | graph_uuid | [embedding of chunk 2] | "## Methods\nWe conducted..." |
| ... | ... | ... | ... |

**Key design**: Segments are full KGDocument objects in the RDF store. The vector table indexes them like any other subject. The parent-segment relationship is maintained via `Edge_hasKGDocumentSegment` in the RDF quad store and can be traversed via SPARQL.

### 5.7 Returning Results as KG Graph Objects

When a vector similarity search matches a segment, the system can reconstruct the full KG graph object representation:

1. **Matched segment** → retrieve as KGDocument object (with all properties)
2. **Parent lookup** → follow `Edge_hasKGDocumentSegment` backward to find parent
3. **Response format** → return in standard KG graph object format:
   - The matched segment KGDocument
   - The `Edge_hasKGDocumentSegment` linking it to parent
   - Optionally the parent KGDocument (for context)

The edge URI for the segment relationship can be derived from an identifier in the index table or constructed deterministically from the parent/segment URIs.

---

## 6. SPARQL Integration for Chunk Retrieval

### 6.1 Using Existing `vg:vectorSimilarity`

Retrieve semantically matching document chunks using the existing SPARQL custom function:

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?segment ?score ?content ?segIndex ?parentDoc WHERE {
    # Find KGDocument segments via vector similarity
    ?segment rdf:type haley:KGDocument .
    ?segment haley:hasKGDocumentSegmentIndex ?segIndex .
    FILTER(?segIndex > 0)
    
    # Vector similarity search on segment content
    BIND(vg:vectorSimilarity(?segment, "search query text", "document_segments") AS ?score)
    FILTER(?score > 0.7)
    
    # Get segment content
    ?segment haley:hasKGDocumentContent ?content .
    
    # Find parent document via edge
    ?edge rdf:type haley:Edge_hasKGDocumentSegment .
    ?edge vital:hasEdgeSource ?parentDoc .
    ?edge vital:hasEdgeDestination ?segment .
}
ORDER BY DESC(?score)
LIMIT 10
```

### 6.2 Parent Document Context Query

After retrieving matching segments, fetch parent context:

```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT ?parent ?headline ?url ?docType WHERE {
    ?edge a haley:Edge_hasKGDocumentSegment .
    ?edge vital:hasEdgeSource ?parent .
    ?edge vital:hasEdgeDestination <matched_segment_uri> .
    
    ?parent haley:hasKGDocumentHeadline ?headline .
    OPTIONAL { ?parent haley:hasKGDocumentURL ?url . }
    OPTIONAL { ?parent haley:hasKGDocumentType ?docType . }
}
```

### 6.3 Full-Text + Vector Hybrid Search on Chunks

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?segment ?hybridScore ?content WHERE {
    ?segment a haley:KGDocument .
    ?segment haley:hasKGDocumentSegmentIndex ?idx .
    FILTER(?idx > 0)
    
    BIND(vg:hybridSearch(?segment, "machine learning transformers", "entity_default", 0.5) AS ?hybridScore)
    FILTER(?hybridScore > 0.3)
    
    ?segment haley:hasKGDocumentContent ?content .
}
ORDER BY DESC(?hybridScore)
LIMIT 20
```

### 6.4 KGQuery Endpoint Integration — `query_type="document"`

**Current gap**: The `query_connections` endpoint (`/api/graphs/kgqueries`) only supports
`query_type="entity"`, which generates SPARQL with `vitaltype` filters targeting
KGEntity subclasses. KGDocument segments have `vitaltype = KGDocument` — a direct
KGNode subclass, **not** a KGEntity subclass. This means `query_connections` with
`VectorSearchCriteria` returns empty results for document segments.

**Workaround**: Use the raw SPARQL endpoint with `vg:vectorSimilarity` (see §6.1).

#### 6.4.1 Design: Separate `_build_document_where_clause`

Add a dedicated `_build_document_where_clause` method to `KGQueryCriteriaBuilder`
rather than parameterizing the existing entity method. This keeps document-specific
concerns (segment filtering, document type property, parent traversal) cleanly
separated from entity query logic.

**Class clause** (replaces the KGEntity UNION):

```python
class_clause = "?entity vital-core:vitaltype haley:KGDocument ."
```

**Document type filter** (analogous to `hasKGEntityType`):

```sparql
?entity haley:hasKGDocumentType <{document_type_uri}> .
```

**Segment scoping** (controlled by `search_scope` enum):

```sparql
-- search_scope="segments":
?entity haley:hasKGDocumentSegmentIndex ?_seg_idx .
FILTER(?_seg_idx > 0)

-- search_scope="summaries":
?entity haley:hasKGDocumentSegmentTypeURI <urn:segtype:segmentation_parent> .

-- search_scope="originals":
FILTER NOT EXISTS { ?entity haley:hasKGDocumentSegmentTypeURI ?_st . }
```

When `search_scope` is `None` or `"all"` (default), no scope filter is applied —
the query returns all document tiers. Use `"segments"` for chunk-level RAG,
`"summaries"` for document-level similarity, `"originals"` for unprocessed docs.

**Reused infrastructure** — the document WHERE clause feeds into the same
`build_entity_query_sparql` / `build_entity_count_query_sparql` query assembly
(SELECT, GRAPH wrapper, ORDER BY, LIMIT/OFFSET). All existing capabilities work
unchanged:
- `vector_criteria` → `BIND(vg:vectorSimilarity(?entity, ...) AS ?vg_score)`
- `multi_vector_criteria` → `BIND(vg:multiVectorSimilarity(...))`
- `geo_criteria` → `BIND(vg:geoDistance(...))`
- `sort_criteria` → frame/slot/property sort bindings
- `entity_property_filters` → direct property filters (works for document properties too)
- `frame_criteria` → frame/slot filtering (if documents have frames attached)
- Pagination, count queries, `count_only` short-circuit

#### 6.4.2 Model Changes

**`kgqueries_model.py`**:
- Allow `query_type = "document"` in `KGQueryCriteria` description/validation
- Add `document_criteria: Optional[DocumentSearchCriteria]` to `KGQueryCriteria`
  (analogous to `source_entity_criteria: EntityQueryCriteria`)
- Add `document_uris: Optional[List[str]]` to `KGQueryResponse`
- Add `DocumentQueryResponse` typed response wrapper (like `KGEntityQueryResponse`)

**`kgentities_model.py`** — Add `DocumentSearchCriteria` Pydantic model:

```python
class DocumentSearchCriteria(BaseModel):
    """Criteria for document queries — document-specific fields that map to
    SPARQL triple patterns in _build_document_where_clause.

    Sits alongside VectorSearchCriteria/GeoSearchCriteria on KGQueryCriteria.
    vector_criteria, multi_vector_criteria, geo_criteria, sort_criteria,
    entity_property_filters, and frame_criteria remain on KGQueryCriteria
    (shared with entity queries).
    """

    # ── Document type filtering ──
    document_type_uri: Optional[str] = Field(
        None,
        description="Filter by hasKGDocumentType URI (e.g. urn:kgdoctype:technical_article). "
                    "Generates: ?entity haley:hasKGDocumentType <uri> ."
    )

    # ── Segment scoping ──
    search_scope: Optional[Literal["all", "segments", "originals", "summaries"]] = Field(
        None,
        description="Controls which tier of documents to search. "
                    "'segments' → segmentIndex > 0 (chunk-level results). "
                    "'summaries' → segmentTypeURI = segmentation_parent (parent copies with summary text). "
                    "'originals' → no segmentTypeURI at all (unprocessed docs). "
                    "'all' / None → no scope filter."
    )

    # ── Segmentation method/type filtering ──
    segment_method_uri: Optional[str] = Field(
        None,
        description="Filter by segmentation method URI (e.g. urn:segmethod:markdown_heading_split). "
                    "Generates: ?entity haley:hasKGDocumentSegmentMethodURI <uri> ."
    )
    segment_type_uri: Optional[str] = Field(
        None,
        description="Filter by segment type URI (e.g. urn:segtype:markdown_section). "
                    "Generates: ?entity haley:hasKGDocumentSegmentTypeURI <uri> ."
    )

    # ── Parent scoping ──
    parent_document_uri: Optional[str] = Field(
        None,
        description="Filter to segments of a specific parent document (via Edge_hasKGDocumentSegment). "
                    "Generates: ?_seg_edge vital-core:hasEdgeSource <uri> . "
                    "?_seg_edge vital-core:hasEdgeDestination ?entity ."
    )

    # ── Content type filtering ──
    content_type: Optional[str] = Field(
        None,
        description="Filter by hasKGContentType (MIME type). "
                    "Generates: ?entity haley:hasKGContentType \"mime_type\" ."
    )

    # ── Token length range ──
    min_token_length: Optional[int] = Field(
        None, ge=0,
        description="Minimum segment token length. "
                    "Generates: ?entity haley:hasKGDocumentSegmentTokenLength ?_tlen . FILTER(?_tlen >= N)"
    )
    max_token_length: Optional[int] = Field(
        None, ge=1,
        description="Maximum segment token length. "
                    "Generates: FILTER(?_tlen <= N)  (reuses ?_tlen from min_token_length or adds binding)"
    )

    # ── Text search ──
    search_text: Optional[str] = Field(
        None,
        description="Full-text search on headline/content. "
                    "Generates: ?entity haley:hasKGDocumentHeadline ?_hl . "
                    "FILTER(CONTAINS(LCASE(?_hl), LCASE(\"text\")))"
    )

    # ── Segmentation-aware response enrichment ──
    include_parent_context: bool = Field(
        False,
        description="When True (and searching segments), follow Edge_hasKGDocumentSegment "
                    "backwards to include the parent document URI and headline in the response. "
                    "Generates an additional OPTIONAL block in the SPARQL query."
    )
    include_original_uri: bool = Field(
        False,
        description="When True (and include_parent_context=True), also follow the "
                    "parent→original edge to return the original document URI. "
                    "Generates a second OPTIONAL hop."
    )
    exclude_managed_segments: bool = Field(
        True,
        description="When True (default), exclude managed segment types from results "
                    "(segmentation_parent, markdown_section, text_chunk) — same as "
                    "GET /api/kgdocuments default behavior. Set False to include all."
    )

    # ── Inline content projection ──
    include_segment_text: bool = Field(
        False,
        description="When True, project segment text directly in the SPARQL query "
                    "(hasKGDocumentContent, hasKGDocumentHeadline) so the response "
                    "contains chunk content without a second fetch. Populates "
                    "DocumentResult.segment_text and .segment_headline."
    )

    # ── Grouping ──
    group_by_document: bool = Field(
        False,
        description="When True, collapse segment results by parent document. "
                    "Returns one DocumentResult per parent, keeping the segment with "
                    "the highest vector score. Requires include_parent_context=True. "
                    "Generates SPARQL GROUP BY ?_parent_doc with MAX(?vg_score) "
                    "and SAMPLE(?entity) aggregation. "
                    "Note: when combined with include_segment_text, the text returned "
                    "is from the SAMPLE'd segment (not guaranteed to be the best-scoring one)."
    )

    # ── Validators ──
    @model_validator(mode='after')
    def _validate_dependencies(self) -> 'DocumentSearchCriteria':
        if self.include_original_uri and not self.include_parent_context:
            raise ValueError(
                "include_original_uri requires include_parent_context=True "
                "(original is resolved via parent → original edge traversal)")
        if self.group_by_document and not self.include_parent_context:
            raise ValueError(
                "group_by_document requires include_parent_context=True "
                "(grouping key is ?_parent_doc from parent context OPTIONAL)")
        return self
```

**Relationship to existing infrastructure**: The `list_segments` method in
`kgdocuments_read_impl.py` already implements a two-hop SPARQL traversal
(original → parent_copy → segments via `Edge_hasKGDocumentSegment`). The
`parent_document_uri` field in `DocumentSearchCriteria` uses the same edge
pattern but in the reverse direction (given a parent, find its segments). The
`include_parent_context` enrichment performs the inverse traversal (given a
segment, find its parent and optionally the original):

```sparql
# include_parent_context OPTIONAL block:
OPTIONAL {
    ?_parent_edge vital-core:hasEdgeSource ?_parent_doc .
    ?_parent_edge vital-core:hasEdgeDestination ?entity .
    ?_parent_doc haley:hasKGDocumentSegmentTypeURI <urn:segtype:segmentation_parent> .
    ?_parent_doc vital-core:hasName ?_parent_name .
}

# include_original_uri OPTIONAL block (chained):
OPTIONAL {
    ?_orig_edge vital-core:hasEdgeSource ?_original_doc .
    ?_orig_edge vital-core:hasEdgeDestination ?_parent_doc .
    FILTER NOT EXISTS {
        ?_original_doc haley:hasKGDocumentSegmentTypeURI ?_ot .
    }
}
```

**JSON example** — search for markdown segments of a specific parent, ranked by vector similarity:

```json
{
  "criteria": {
    "query_type": "document",
    "document_criteria": {
      "search_scope": "segments",
      "segment_method_uri": "urn:segmethod:markdown_heading_split",
      "parent_document_uri": "urn:doc:abc123"
    },
    "vector_criteria": {
      "search_text": "solar panel efficiency",
      "index_name": "document_segments",
      "top_k": 10
    }
  },
  "page_size": 10,
  "offset": 0
}
```

#### 6.4.3 Query Builder Changes

**`kg_query_builder.py`** — Add `DocumentQueryCriteria` dataclass and methods to
`KGQueryCriteriaBuilder`:

```python
@dataclass
class DocumentQueryCriteria:
    """Builder-side criteria for document queries (mirrors DocumentSearchCriteria)."""
    # Document-specific filtering
    document_type_uri: Optional[str] = None
    search_scope: Optional[str] = None  # "all", "segments", "originals", "summaries"
    segment_method_uri: Optional[str] = None
    segment_type_uri: Optional[str] = None
    parent_document_uri: Optional[str] = None
    content_type: Optional[str] = None
    min_token_length: Optional[int] = None
    max_token_length: Optional[int] = None
    search_text: Optional[str] = None
    # Segmentation-aware response enrichment
    include_parent_context: bool = False
    include_original_uri: bool = False
    exclude_managed_segments: bool = True
    # Inline content projection
    include_segment_text: bool = False
    # Grouping
    group_by_document: bool = False
    # Shared criteria (passed through from KGQueryCriteria)
    document_uris: Optional[List[str]] = None
    entity_property_filters: Optional[List[EntityPropertyFilter]] = None
    frame_criteria: Optional[List[FrameCriteria]] = None
    sort_criteria: Optional[List[SortCriteria]] = None
    vector_criteria: Optional[VectorCriteria] = None
    multi_vector_criteria: Optional[MultiVectorCriteria] = None
    geo_criteria: Optional[GeoCriteria] = None
```

**`_build_document_where_clause`** — Each `DocumentSearchCriteria` field maps to
a specific SPARQL pattern:

```python
def _build_document_where_clause(self, criteria: DocumentQueryCriteria) -> str:
    """Build WHERE clause for document queries.

    Uses vitaltype = KGDocument instead of KGEntity subclass UNION.
    Each DocumentSearchCriteria field generates a specific SPARQL pattern.
    """
    class_clause = "?entity vital-core:vitaltype haley:KGDocument ."
    filter_clauses = []

    # Document type: hasKGDocumentType
    if criteria.document_type_uri:
        filter_clauses.append(
            f"?entity haley:hasKGDocumentType <{criteria.document_type_uri}> .")

    # Resolve search_scope
    scope = criteria.search_scope

    if scope == "segments":
        # Chunk-level segments only (segmentIndex > 0)
        filter_clauses.append(
            "?entity haley:hasKGDocumentSegmentIndex ?_seg_idx .")
        filter_clauses.append("FILTER(?_seg_idx > 0)")
    elif scope == "summaries":
        # Parent copies (the segmentation_parent tier)
        filter_clauses.append(
            '?entity haley:hasKGDocumentSegmentTypeURI '
            '<urn:segtype:segmentation_parent> .')
    elif scope == "originals":
        # Unprocessed originals (no segmentTypeURI at all)
        filter_clauses.append(
            "FILTER NOT EXISTS { ?entity haley:hasKGDocumentSegmentTypeURI ?_st . }")
    # scope == "all" or None → no scope filter

    # Segmentation method filter
    if criteria.segment_method_uri:
        filter_clauses.append(
            f"?entity haley:hasKGDocumentSegmentMethodURI <{criteria.segment_method_uri}> .")

    # Segment type filter
    if criteria.segment_type_uri:
        filter_clauses.append(
            f"?entity haley:hasKGDocumentSegmentTypeURI <{criteria.segment_type_uri}> .")

    # Parent document filter (segments of a specific parent)
    if criteria.parent_document_uri:
        filter_clauses.append(
            "?_seg_edge vital-core:vitaltype haley:Edge_hasKGDocumentSegment .")
        filter_clauses.append(
            f"?_seg_edge vital-core:hasEdgeSource <{criteria.parent_document_uri}> .")
        filter_clauses.append(
            "?_seg_edge vital-core:hasEdgeDestination ?entity .")

    # Content type
    if criteria.content_type:
        filter_clauses.append(
            f'?entity haley:hasKGContentType "{criteria.content_type}" .')

    # Token length range
    if criteria.min_token_length is not None or criteria.max_token_length is not None:
        filter_clauses.append(
            "?entity haley:hasKGDocumentSegmentTokenLength ?_tlen .")
        if criteria.min_token_length is not None:
            filter_clauses.append(f"FILTER(?_tlen >= {criteria.min_token_length})")
        if criteria.max_token_length is not None:
            filter_clauses.append(f"FILTER(?_tlen <= {criteria.max_token_length})")

    # Headline text search
    if criteria.search_text:
        filter_clauses.append("?entity haley:hasKGDocumentHeadline ?_hl .")
        filter_clauses.append(
            f'FILTER(CONTAINS(LCASE(STR(?_hl)), LCASE("{criteria.search_text}")))')

    # URI filter
    if criteria.document_uris:
        uri_list = " ".join([f"<{uri}>" for uri in criteria.document_uris])
        filter_clauses.append(f"VALUES ?entity {{ {uri_list} }}")

    # Exclude managed segment types (segmentation_parent, markdown_section, text_chunk)
    # Same behavior as GET /api/kgdocuments default (see _MANAGED_SEGMENT_TYPES
    # in kgdocuments_read_impl.py)
    if criteria.exclude_managed_segments:
        filter_clauses.append(
            'FILTER NOT EXISTS { '
            '?entity haley:hasKGDocumentSegmentTypeURI ?_mst . '
            'FILTER(?_mst IN ('
            '<urn:segtype:segmentation_parent>, '
            '<urn:segtype:markdown_section>, '
            '<urn:segtype:text_chunk>'
            ')) }')

    # Reuse entity_property_filters (same logic as entity path)
    if criteria.entity_property_filters:
        # ... same as _build_entity_where_clause property filter loop
        ...

    # Reuse frame_criteria (same logic as entity path)
    if criteria.frame_criteria:
        # ... same as _build_entity_where_clause frame/slot loop
        ...

    where_clauses = [class_clause] + filter_clauses

    # Inline segment text projection (avoids N+1 fetches for RAG)
    if criteria.include_segment_text:
        where_clauses.append(
            '?entity haley:hasKGDocumentContent ?_seg_content .')
        where_clauses.append(
            'OPTIONAL { ?entity haley:hasKGDocumentHeadline ?_seg_headline . }')

    # Segmentation-aware OPTIONAL projections (added after main WHERE body)
    # These add ?_parent_doc, ?_parent_name, ?_original_doc to SELECT
    # Uses same Edge_hasKGDocumentSegment traversal as list_segments in
    # kgdocuments_read_impl.py but in reverse (segment → parent → original)
    if criteria.include_parent_context:
        where_clauses.append(
            'OPTIONAL { '
            '?_parent_edge vital-core:hasEdgeSource ?_parent_doc . '
            '?_parent_edge vital-core:hasEdgeDestination ?entity . '
            '?_parent_doc haley:hasKGDocumentSegmentTypeURI '
            '<urn:segtype:segmentation_parent> . '
            '?_parent_doc vital-core:hasName ?_parent_name . }')
        if criteria.include_original_uri:
            where_clauses.append(
                'OPTIONAL { '
                '?_orig_edge vital-core:hasEdgeSource ?_original_doc . '
                '?_orig_edge vital-core:hasEdgeDestination ?_parent_doc . '
                'FILTER NOT EXISTS { '
                '?_original_doc haley:hasKGDocumentSegmentTypeURI ?_ot . '
                '} }')

    return " ".join(where_clauses)
```

**Query assembly methods** — same signature pattern as entity queries:

```python
def build_document_query_sparql(self, criteria: DocumentQueryCriteria,
                                 graph_id: str, page_size: int,
                                 offset: int) -> str:
    """Build paginated SPARQL query for document search.

    When group_by_document=True, generates a GROUP BY query that collapses
    results by parent document, keeping the best-scoring segment per parent.
    """
    where_clause = self._build_document_where_clause(criteria)

    if criteria.group_by_document:
        # Grouped query: one row per parent document, best segment per parent
        return self._build_document_grouped_query(criteria, where_clause,
                                                  graph_id, page_size, offset)
    # Same query assembly as build_entity_query_sparql:
    # sort bindings, vector/geo clauses, SELECT, GRAPH, ORDER BY, LIMIT
    ...

def _build_document_grouped_query(self, criteria: DocumentQueryCriteria,
                                    where_clause: str, graph_id: str,
                                    page_size: int, offset: int) -> str:
    """Build SPARQL with GROUP BY ?_parent_doc for document-level dedup.

    Generated SPARQL shape:
      SELECT ?_parent_doc (SAMPLE(?entity) AS ?_best_seg)
             (MAX(?vg_score) AS ?_max_score)
             (SAMPLE(?_parent_name) AS ?_parent_name)
             (SAMPLE(?_original_doc) AS ?_original_doc)
      WHERE {
        GRAPH <graph_id> {
          <where_clause>    # includes parent context OPTIONAL blocks
          BIND(vg:vectorSimilarity(?entity, ...) AS ?vg_score)
          FILTER(?vg_score > min_score)
        }
      }
      GROUP BY ?_parent_doc
      ORDER BY DESC(?_max_score)
      LIMIT page_size OFFSET offset

    Notes:
    - SAMPLE(?entity) picks an arbitrary segment per group; in practice
      the segment with MAX(?vg_score) is not guaranteed to be the one
      returned by SAMPLE. If exact best-segment is needed, use a subquery:

        SELECT ?_parent_doc ?entity ?vg_score WHERE {
          { SELECT ?_parent_doc (MAX(?vg_score) AS ?_max_score)
            WHERE { ... } GROUP BY ?_parent_doc }
          ... re-join to get the segment with ?vg_score = ?_max_score
        }

      For v1, SAMPLE is acceptable since the primary use case is
      document-level ranking, not identifying the exact best chunk.
    """
    ...

def build_document_count_query_sparql(self, criteria: DocumentQueryCriteria,
                                       graph_id: str) -> str:
    """Build COUNT query for document search.

    When group_by_document=True, counts distinct parent documents
    rather than individual segments.
    """
    where_clause = self._build_document_where_clause(criteria)
    if criteria.group_by_document:
        # COUNT(DISTINCT ?_parent_doc)
        ...
    else:
        # COUNT(?entity)
        ...
```

**Exact-best-segment variant** (future enhancement): If the caller needs the exact
highest-scoring segment per parent (not just any segment), use a correlated subquery:

```sparql
SELECT ?_parent_doc ?entity ?vg_score ?_parent_name ?_original_doc
WHERE {
  {
    SELECT ?_parent_doc (MAX(?_inner_score) AS ?_max_score)
    WHERE {
      GRAPH <graph_id> {
        ?entity vital-core:vitaltype haley:KGDocument .
        ?entity haley:hasKGDocumentSegmentIndex ?_seg_idx . FILTER(?_seg_idx > 0)
        BIND(vg:vectorSimilarity(?entity, "query text", "document_segments") AS ?_inner_score)
        FILTER(?_inner_score > 0.3)
        ?_parent_edge vital-core:hasEdgeSource ?_parent_doc .
        ?_parent_edge vital-core:hasEdgeDestination ?entity .
        ?_parent_doc haley:hasKGDocumentSegmentTypeURI <urn:segtype:segmentation_parent> .
      }
    }
    GROUP BY ?_parent_doc
  }
  GRAPH <graph_id> {
    ?entity vital-core:vitaltype haley:KGDocument .
    BIND(vg:vectorSimilarity(?entity, "query text", "document_segments") AS ?vg_score)
    FILTER(?vg_score = ?_max_score)
    ?_parent_edge2 vital-core:hasEdgeSource ?_parent_doc .
    ?_parent_edge2 vital-core:hasEdgeDestination ?entity .
    ?_parent_doc vital-core:hasName ?_parent_name .
    OPTIONAL {
      ?_orig_edge vital-core:hasEdgeSource ?_original_doc .
      ?_orig_edge vital-core:hasEdgeDestination ?_parent_doc .
      FILTER NOT EXISTS { ?_original_doc haley:hasKGDocumentSegmentTypeURI ?_ot . }
    }
  }
}
ORDER BY DESC(?vg_score)
LIMIT 10
```

This is deferred to a later phase; v1 uses SAMPLE which is sufficient for
document-level ranking.

**Refactoring opportunity**: Extract the shared query assembly logic (sort bindings,
vector/geo clauses, SELECT wrapper, GRAPH wrapper, LIMIT/OFFSET) from
`build_entity_query_sparql` into a private `_assemble_paginated_query` helper.
Both `build_entity_query_sparql` and `build_document_query_sparql` call it with
their respective WHERE clauses. Same for count queries.

#### SPARQL ↔ Criteria Mapping Summary

| `DocumentSearchCriteria` field | SPARQL pattern generated |
|---|---|
| `document_type_uri` | `?entity haley:hasKGDocumentType <uri> .` |
| `search_scope="segments"` | `?entity haley:hasKGDocumentSegmentIndex ?_idx . FILTER(?_idx > 0)` |
| `search_scope="summaries"` | `?entity haley:hasKGDocumentSegmentTypeURI <urn:segtype:segmentation_parent> .` |
| `search_scope="originals"` | `FILTER NOT EXISTS { ?entity haley:hasKGDocumentSegmentTypeURI ?_st . }` |
| `search_scope="all"` / `None` | *(no scope filter)* |
| `segment_method_uri` | `?entity haley:hasKGDocumentSegmentMethodURI <uri> .` |
| `segment_type_uri` | `?entity haley:hasKGDocumentSegmentTypeURI <uri> .` |
| `parent_document_uri` | `?_seg_edge vitaltype Edge_hasKGDocumentSegment . ?_seg_edge hasEdgeSource <uri> . ?_seg_edge hasEdgeDestination ?entity .` |
| `content_type` | `?entity haley:hasKGContentType "mime" .` |
| `min_token_length` / `max_token_length` | `?entity haley:hasKGDocumentSegmentTokenLength ?_tlen . FILTER(?_tlen >= N) FILTER(?_tlen <= M)` |
| `search_text` | `?entity haley:hasKGDocumentHeadline ?_hl . FILTER(CONTAINS(LCASE(?_hl), ...))` |
| `exclude_managed_segments=True` | `FILTER NOT EXISTS { ?entity haley:hasKGDocumentSegmentTypeURI ?_mst . FILTER(?_mst IN (...managed types...)) }` |
| `include_parent_context=True` | `OPTIONAL { ?_parent_edge hasEdgeSource ?_parent_doc . ?_parent_edge hasEdgeDestination ?entity . ... }` |
| `include_original_uri=True` | `OPTIONAL { ?_orig_edge hasEdgeSource ?_original_doc . ?_orig_edge hasEdgeDestination ?_parent_doc . ... }` |
| `include_segment_text=True` | `?entity haley:hasKGDocumentContent ?_seg_content . OPTIONAL { ?entity haley:hasKGDocumentHeadline ?_seg_headline . }` |
| `group_by_document=True` | `GROUP BY ?_parent_doc` + `MAX(?vg_score)` + `SAMPLE(?entity)` |
| `vector_criteria` *(shared)* | `BIND(vg:vectorSimilarity(?entity, "text", "index") AS ?vg_score)` |
| `geo_criteria` *(shared)* | `BIND(vg:geoDistance(?entity, lat, lon) AS ?vg_distance)` |

#### 6.4.4 Endpoint Changes

**`kgquery_endpoint.py`**:

```python
# In _query_connections validation:
if query_type not in ["relation", "frame", "entity", "frame_query", "document"]:
    raise HTTPException(status_code=400, ...)

# New dispatch:
elif query_type == "document":
    return await self._execute_document_query(backend, space_id, graph_id, query_request)
```

`_execute_document_query` follows the same pattern as `_execute_entity_query`:
1. Convert `criteria.document_criteria` (Pydantic `DocumentSearchCriteria`) →
   builder `DocumentQueryCriteria` dataclass
2. Merge shared fields from `KGQueryCriteria` (`vector_criteria`, `geo_criteria`,
   `multi_vector_criteria`, `sort_criteria`, `entity_property_filters`,
   `frame_criteria`) into the builder dataclass
3. Call `build_document_query_sparql` + `build_document_count_query_sparql`
   - When `group_by_document=True`, the builder generates a GROUP BY query;
     the endpoint extracts `?_parent_doc`, `?_best_seg`, `?_max_score`,
     `?_parent_name`, `?_original_doc` from SPARQL bindings
4. Execute SPARQL, build response:
   - **Default path** (no grouping, no enrichment): extract `?entity` URIs →
     `document_uris=[...]`
   - **Enriched path** (`include_parent_context=True`): extract all projected
     variables → build `DocumentResult` list with `score`, `parent_document_uri`,
     `parent_document_name`, `original_document_uri` → `document_results=[...]`
   - **Grouped path** (`group_by_document=True`): extract grouped bindings →
     build `DocumentResult` per parent with `document_uri=?_best_seg`,
     `score=?_max_score`, parent/original context → `document_results=[...]`
5. Return `KGQueryResponse(query_type="document", document_uris=[...],
   document_results=[...] if enriched/grouped)`

#### 6.4.5 Client Changes

**`kgqueries_endpoint.py`** — Add `query_documents()` convenience method:

```python
async def query_documents(
    self,
    space_id: str,
    graph_id: str,
    # Document-specific criteria (all map to SPARQL patterns)
    document_type_uri: Optional[str] = None,
    search_scope: Optional[Literal["all", "segments", "originals", "summaries"]] = None,
    segment_method_uri: Optional[str] = None,
    segment_type_uri: Optional[str] = None,
    parent_document_uri: Optional[str] = None,
    content_type: Optional[str] = None,
    min_token_length: Optional[int] = None,
    max_token_length: Optional[int] = None,
    search_text: Optional[str] = None,
    document_uris: Optional[List[str]] = None,
    # Segmentation-aware response enrichment
    include_parent_context: bool = False,
    include_original_uri: bool = False,
    exclude_managed_segments: bool = True,
    include_segment_text: bool = False,
    group_by_document: bool = False,
    # Shared criteria (same as entity queries)
    vector_criteria: Optional[VectorSearchCriteria] = None,
    multi_vector_criteria: Optional[MultiVectorSearchCriteria] = None,
    geo_criteria: Optional[GeoSearchCriteria] = None,
    sort_criteria: Optional[List[SortCriteria]] = None,
    entity_property_filters: Optional[List[EntityPropertyFilter]] = None,
    frame_criteria: Optional[List[FrameCriteria]] = None,
    # Pagination
    page_size: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> DocumentQueryResponse:
    """Query KGDocuments matching criteria. Returns document URIs.

    Document-specific fields are packed into DocumentSearchCriteria;
    shared fields (vector, geo, sort, etc.) go on KGQueryCriteria.
    """
    doc_criteria = DocumentSearchCriteria(
        document_type_uri=document_type_uri,
        search_scope=search_scope,
        segment_method_uri=segment_method_uri,
        segment_type_uri=segment_type_uri,
        parent_document_uri=parent_document_uri,
        content_type=content_type,
        min_token_length=min_token_length,
        max_token_length=max_token_length,
        search_text=search_text,
        include_parent_context=include_parent_context,
        include_original_uri=include_original_uri,
        exclude_managed_segments=exclude_managed_segments,
        include_segment_text=include_segment_text,
        group_by_document=group_by_document,
    )
    criteria = KGQueryCriteria(
        query_type="document",
        document_criteria=doc_criteria,
        source_entity_uris=document_uris,
        vector_criteria=vector_criteria,
        multi_vector_criteria=multi_vector_criteria,
        geo_criteria=geo_criteria,
        sort_criteria=sort_criteria,
        entity_property_filters=entity_property_filters,
        frame_criteria=frame_criteria,
    )
    raw = await self.query_connections(
        space_id=space_id, graph_id=graph_id,
        criteria=criteria, page_size=page_size,
        offset=offset, count_only=count_only,
    )
    return DocumentQueryResponse.from_raw(raw)
```

**`kgqueries_model.py`** — Add typed response:

```python
class DocumentResult(BaseModel):
    """A single document result with optional parent/original context."""
    document_uri: str = Field(..., description="Document or segment URI")
    score: Optional[float] = Field(None, description="Vector similarity or hybrid score (when vector_criteria used)")
    segment_text: Optional[str] = Field(None, description="Segment chunk text (when include_segment_text=True)")
    segment_headline: Optional[str] = Field(None, description="Segment heading (when include_segment_text=True)")
    parent_document_uri: Optional[str] = Field(None, description="Parent copy URI (when include_parent_context=True)")
    parent_document_name: Optional[str] = Field(None, description="Parent copy name (when include_parent_context=True)")
    original_document_uri: Optional[str] = Field(None, description="Original document URI (when include_original_uri=True)")


class DocumentQueryResponse(BasePaginatedResponse):
    """Typed response from query_documents() — Case 4 (document as top-most object)."""
    document_uris: List[str] = Field(default_factory=list, description="Flat list of document/segment URIs")
    document_results: Optional[List[DocumentResult]] = Field(
        None, description="Enriched results with parent context (populated when include_parent_context=True)")

    @classmethod
    def from_raw(cls, raw: 'KGQueryResponse') -> 'DocumentQueryResponse':
        return cls(
            document_uris=raw.document_uris or [],
            document_results=raw.document_results,
            total_count=raw.total_count,
            page_size=raw.page_size,
            offset=raw.offset,
        )
```

#### 6.4.6 Example Usage

```python
# Search document segments by vector similarity
resp = await vg_client.kgqueries.query_documents(
    space_id=space_id,
    graph_id=graph_id,
    search_scope="segments",
    vector_criteria=VectorSearchCriteria(
        search_text="solar panel efficiency",
        index_name="document_segments",
        top_k=10,
    ),
)
# resp.document_uris → [segment URIs ranked by similarity]

# Search all documents (originals + segments) by type
resp = await vg_client.kgqueries.query_documents(
    space_id=space_id,
    graph_id=graph_id,
    document_type_uri="urn:kgdoctype:technical_article",
    page_size=20,
)

# Find segments of a specific parent, filtered by method
resp = await vg_client.kgqueries.query_documents(
    space_id=space_id,
    graph_id=graph_id,
    parent_document_uri="urn:doc:abc123",
    segment_method_uri="urn:segmethod:markdown_heading_split",
    min_token_length=100,
    max_token_length=600,
)

# Count original documents only (exclude parents and segments)
resp = await vg_client.kgqueries.query_documents(
    space_id=space_id,
    graph_id=graph_id,
    search_scope="originals",
    count_only=True,
)
# resp.total_count → number of original documents

# RAG-ready: vector search with inline segment text (single round-trip)
resp = await vg_client.kgqueries.query_documents(
    space_id=space_id,
    graph_id=graph_id,
    search_scope="segments",
    include_segment_text=True,
    include_parent_context=True,
    include_original_uri=True,
    vector_criteria=VectorSearchCriteria(
        search_text="transformer architecture attention mechanism",
        index_name="document_segments",
        top_k=5,
    ),
)
# resp.document_results → [
#   DocumentResult(
#     document_uri="urn:doc:abc_parent_markdown_heading_split_seg_3",
#     score=0.82,
#     segment_text="The transformer architecture uses self-attention...",
#     segment_headline="3. Self-Attention Mechanism",
#     parent_document_uri="urn:doc:abc_parent_markdown_heading_split",
#     parent_document_name="My Paper [Segments: markdown_heading_split]",
#     original_document_uri="urn:doc:abc",
#   ), ...  (ranked by similarity, text included inline)
# ]

# Grouped search: one result per document, best segment per doc (RAG dedup)
resp = await vg_client.kgqueries.query_documents(
    space_id=space_id,
    graph_id=graph_id,
    search_scope="segments",
    include_parent_context=True,
    include_original_uri=True,
    group_by_document=True,
    vector_criteria=VectorSearchCriteria(
        search_text="transformer architecture attention mechanism",
        index_name="document_segments",
        top_k=20,  # over-fetch then collapse by parent
    ),
)
# resp.document_results → [
#   DocumentResult(
#     document_uri="urn:doc:abc_parent_..._seg_3",  # SAMPLE best segment
#     score=0.82,  # MAX score across all segments of this parent
#     parent_document_uri="urn:doc:abc_parent_...",
#     parent_document_name="My Paper",
#     original_document_uri="urn:doc:abc",
#   ),
#   DocumentResult(
#     document_uri="urn:doc:xyz_parent_..._seg_7",
#     score=0.71,
#     parent_document_uri="urn:doc:xyz_parent_...",
#     parent_document_name="Other Paper",
#     original_document_uri="urn:doc:xyz",
#   ),
# ]  # collapsed: one entry per parent doc, ranked by best segment score

# Summary-level search (search parent copies by their summary text)
resp = await vg_client.kgqueries.query_documents(
    space_id=space_id,
    graph_id=graph_id,
    search_scope="summaries",
    vector_criteria=VectorSearchCriteria(
        search_text="machine learning survey paper",
        index_name="document_segments",
        top_k=5,
    ),
)
# resp.document_uris → [parent copy URIs ranked by summary similarity]

# JSON request equivalent of the first example:
# POST /api/graphs/kgqueries?space_id=...&graph_id=...
# {
#   "criteria": {
#     "query_type": "document",
#     "document_criteria": {
#       "search_scope": "segments"
#     },
#     "vector_criteria": {
#       "search_text": "solar panel efficiency",
#       "index_name": "document_segments",
#       "top_k": 10
#     }
#   },
#   "page_size": 10,
#   "offset": 0
# }
```

#### 6.4.7 Files Changed

| File | Change |
|---|---|
| `vitalgraph/model/kgentities_model.py` | Add `DocumentSearchCriteria` Pydantic model |
| `vitalgraph/model/kgqueries_model.py` | Add `"document"` to `query_type`, `document_criteria` to `KGQueryCriteria`, `document_uris` to response, `DocumentQueryResponse` |
| `vitalgraph/sparql/kg_query_builder.py` | Add `DocumentQueryCriteria` dataclass, `_build_document_where_clause`, `build_document_query_sparql`, `build_document_count_query_sparql` |
| `vitalgraph/endpoint/kgquery_endpoint.py` | Add `"document"` to validation, `_execute_document_query` method |
| `vitalgraph/client/endpoint/kgqueries_endpoint.py` | Add `query_documents()` convenience method |
| `vitalgraph-client-ts/src/endpoint/KGQueriesEndpoint.ts` | Add `queryDocuments()` method with `DocumentSearchCriteria` interface and `DocumentResult` / `DocumentQueryResponse` types |

**Prerequisite**: Issue #015 (deferred UUID resolution) is fixed — `vg:vectorSimilarity`
now works correctly regardless of BIND/triple ordering in generated SPARQL.

#### 6.4.8 Design Notes

1. **No legacy boolean aliases**: `segments_only` and `originals_only` are removed.
   Use `search_scope` exclusively. This avoids ambiguous combinations and keeps
   the API surface clean.

2. **Pydantic validators enforce dependencies**:
   - `include_original_uri=True` requires `include_parent_context=True`
     (original is resolved via the parent → original edge hop)
   - `group_by_document=True` requires `include_parent_context=True`
     (GROUP BY key is `?_parent_doc` from the parent context OPTIONAL)

3. **`group_by_document` + `include_segment_text`**: Allowed but the text
   returned is from the SAMPLE’d segment, not guaranteed to be the
   highest-scoring one. This is a documented caveat acceptable for v1.
   The exact-best-segment variant (correlated subquery) is deferred.

4. **`/api/kgdocuments/search` (\u00a77.3) removed**: Superseded by `query_type="document"`
   on `/api/graphs/kgqueries` which provides richer criteria,
   `include_segment_text` for inline RAG content, and `group_by_document`
   for dedup. Full document tree retrieval is handled by
   `GET /api/kgdocuments?include_segments=true` (new §7.3).
   Note: this endpoint was plan-only (never implemented) — no tests,
   client methods, or UI screens reference it, so no cleanup is needed.

5. **TypeScript client**: `vitalgraph-client-ts` needs a matching
   `queryDocuments()` method on `KGQueriesEndpoint.ts`, with a
   `DocumentSearchCriteria` interface mirroring the Python Pydantic model
   and `DocumentResult` / `DocumentQueryResponse` response types.

---

## 7. API Endpoints

### 7.1 REST Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/spaces/{space}/graphs/{graph}/kgdocuments` | List documents (paginated) |
| GET | `/api/spaces/{space}/graphs/{graph}/kgdocuments/{uri}` | Get single document |
| POST | `/api/spaces/{space}/graphs/{graph}/kgdocuments` | Create document(s) |
| PUT | `/api/spaces/{space}/graphs/{graph}/kgdocuments` | Update document(s) |
| DELETE | `/api/spaces/{space}/graphs/{graph}/kgdocuments/{uri}` | Delete document |
| GET | `/api/spaces/{space}/graphs/{graph}/kgdocuments/{uri}/segments` | List segments of a document |
| POST | `/api/spaces/{space}/graphs/{graph}/kgdocuments/{uri}/segment` | Trigger segmentation |

### 7.2 Segmentation Endpoint

```
POST /api/spaces/{space}/graphs/{graph}/kgdocuments/{uri}/segment
Body:
{
    "method": "markdown",           // segmentation method
    "max_segment_tokens": 512,
    "min_segment_tokens": 50,
    "overlap_tokens": 0,
    "heading_levels": [1, 2, 3],
    "auto_vectorize": true          // trigger vectorization after segmentation
}
Response:
{
    "parent_uri": "urn:doc:abc123",
    "segments_created": 12,
    "total_tokens": 5000,
    "segment_method_uri": "urn:segmethod:markdown_512"
}
```

### 7.3 Document Tree Expansion (`include_segments`)

The single-document GET supports an `include_segments` query parameter that
returns the full segmented document tree in one call:

```
GET /api/kgdocuments?space_id=...&graph_id=...&uri=<original_uri>&include_segments=true

Response:
{
    "results": [
        { /* Original KGDocument object */ },
        { /* Parent copy KGDocument (segmentation_parent) */ },
        { /* Edge_hasKGDocumentSegment: original → parent */ },
        { /* Segment 1 KGDocument */ },
        { /* Edge_hasKGDocumentSegment: parent → segment 1 */ },
        { /* Segment 2 KGDocument */ },
        { /* Edge_hasKGDocumentSegment: parent → segment 2 */ },
        ...
    ],
    "total_count": 27
}
```

**Implementation**: When `include_segments=True`:
1. Fetch the original document triples
2. Run the existing `list_segments` SPARQL traversal (original → parent → segments)
3. Fetch full triples for parent copy + all segments + all edges
4. Return all objects in a single flat `results` list

This reuses `KGDocumentsReadProcessor.list_segments()` and
`GraphObjectRetriever.get_objects_by_uris()` — no new SPARQL needed.

**Search use case**: Document search is handled by `query_type="document"` on
`/api/graphs/kgqueries` (§6.4). The `include_segment_text` flag provides
inline chunk content for RAG without a separate search endpoint.

---

## 8. Implementation Phases

### Phase 1: UI Screen (Low complexity)
- Add KG Documents navigation item to sidebar
- Create `KGDocuments.tsx` list page
- Add document detail view with content display
- Wire up to existing objects endpoint (KGDocument is a graph object)

### Phase 2: Vector Indexing Completion (Low complexity)
- Ensure `kgdocument` mapping rows are created in default space setup
- Add `source_type = 'document_content'` handling in `search_text_builder.py`
- Verify auto-sync triggers on KGDocument CRUD

### Phase 3: Segmentation Pipeline (Medium complexity)
- Implement `MarkdownSegmentConfig` and segmentation logic
- Create `document_segmenter.py` module
- Implement segment KGDocument creation with proper properties
- Implement `Edge_hasKGDocumentSegment` creation
- Add `/segment` API endpoint
- Vectorize segments on creation

### Phase 4: Search Integration (Medium complexity)
- Add `/kgdocuments/search` endpoint
- Implement parent-segment traversal in results
- Return results in KG graph object format (segment + edge + parent)
- UI integration: search interface on KG Documents page

### Phase 5: UI Enhancements (Low complexity)
- Segment viewer: display segments with highlighting
- Parent-child navigation in detail view
- Search results with score display and context preview
- Segment count indicators in list view

---

## 9. File Locations

| Component | Path | Status |
|---|---|---|
| Package init | `vitalgraph/document/__init__.py` | ✅ Done |
| Segmentation logic | `vitalgraph/document/document_segmenter.py` | ✅ Done |
| Segment config | `vitalgraph/document/segment_config.py` | ✅ Done |
| Three-tier processor | `vitalgraph/document/kgdocument_segmentation_processor.py` | ✅ Done |
| Config manager (DB) | `vitalgraph/document/segmentation_config_manager.py` | ✅ Done |
| Auto-segmentation hook | `vitalgraph/document/auto_segmentation.py` | ✅ Done |
| Vector index setup | `vitalgraph/document/vector_index_setup.py` | ✅ Done |
| API endpoint (segmentation) | `vitalgraph/endpoint/kgdocuments_endpoint.py` | ✅ Done |
| API endpoint (CRUD) | `vitalgraph/endpoint/kgdocuments_endpoint.py` (GET/POST/PUT/DELETE) | ✅ Done |
| Read processor | `vitalgraph/kg_impl/kgdocuments_read_impl.py` | ✅ Done |
| Write protection | Rejects external writes to managed segments/parents | ✅ Done |
| Server wiring | `vitalgraph/impl/vitalgraphapp_impl.py` (router registered) | ✅ Done |
| Pydantic models | `vitalgraph/model/kgdocuments_model.py` | ✅ Done |
| Frontend page | `frontend/src/pages/KGDocuments.tsx` | ✅ Done |
| Frontend routing | `frontend/src/App.tsx` (routes added) | ✅ Done |
| Sidebar nav | `frontend/src/components/Layout.tsx` (item added) | ✅ Done |
| Client endpoint | `vitalgraph/client/endpoint/kgdocuments_endpoint.py` | ✅ Done |
| Client response models | `vitalgraph/client/response/client_response.py` (KGDocument*Response) | ✅ Done |
| Client interface | `vitalgraph/client/vitalgraph_client_inf.py` (abstract methods) | ✅ Done |
| Client delegation | `vitalgraph/client/vitalgraph_client.py` (convenience methods) | ✅ Done |
| Vector convenience wrappers | `setup_document_segments_index/mapping/reindex` on client | ✅ Done |
| Frontend detail | `frontend/src/pages/KGDocumentDetail.tsx` | ✅ Done |
| Background job queue | `vitalgraph/document/segmentation_job_manager.py` + `segmentation_worker.py` | ✅ Done |
| Segmentation status endpoint | `GET /api/graphs/kgdocuments/segmentation-status` | ✅ Done |
| Worker startup/shutdown | `vitalgraph/impl/vitalgraphapp_impl.py` (startup_event) | ✅ Done |
| Client segmentation status | `get_segmentation_status()` on client endpoint + interface + delegation | ✅ Done |

---

## 10. Dependencies & Considerations

- **Token counting**: Use the same tokenizer as the configured vector provider (e.g., the HuggingFace tokenizer for the embedding model). This ensures segment token budgets align with the model's actual input window and avoids over/under-splitting.
- **Text splitting**: Either use LangChain (`MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter`) or implement equivalent in-house logic (regex heading detection + recursive paragraph/sentence/word splitting) to avoid the dependency.
- **Re-segmentation**: If a parent document is updated, existing segments should be cleared and re-created
- **Segment deletion**: Deleting a parent document should cascade-delete all segments and their edges
- **Large documents**: For very large documents (>100k tokens), segmentation should be batched
- **Vector index capacity**: Many segments per document → significantly more vector rows; monitor index performance
- **Overlap handling**: Token overlap between segments improves retrieval but increases storage; make configurable

---

## 11. Implementation Status (June 2026)

### Completed

| Phase | Description | Tests |
|---|---|---|
| Phase 1 | Document segmenter module (markdown + plain recursive splitters) | 7/7 pass |
| Phase 2 | Segmentation config table + async CRUD manager | — |
| Phase 3 | KGDocument segmentation REST endpoint + processor | 8/8 pass |
| Phase 4 | Auto-segmentation hook (on document CRUD) | — |
| Phase 5 | Vector index setup (`document_segments` HNSW index + mapping) | — |
| Phase 6 | UI — KG Documents page + sidebar nav | — |
| Phase 7 | Dedicated CRUD endpoints (GET/POST/PUT/DELETE) + read processor | — |
| Phase 8 | Write protection for managed segments/parents | — |
| Phase 9 | Server wiring in VitalGraphAppImpl | — |
| Phase 10 | Python client endpoint + response models + vector convenience wrappers | — |
| Phase 11 | Background job queue + segmentation worker + status endpoint + client method | — |
| Phase 12 | Quad-level detection hook (auto re-segmentation on SPARQL UPDATE) | — |
| Phase 13 | UI: Segmentation status badge (detail page) + retry button + auto-poll | — |
| Phase 14 | UI: Segmentation status column (list page) + auto-poll active jobs | — |
| Phase 15 | Frontend ApiService: `getSegmentationStatus` + `segmentDocument` methods | — |
| Phase 16 | Command palette: KG Documents in search results | — |
| Phase 17 | NOTIFY/LISTEN optimization for instant worker wake | — |
| Phase 18 | Content hash comparison — skip re-segmentation when content unchanged | — |
| Phase 19 | Vector index bootstrap — auto-create `document_segments` HNSW on space init | — |
| Phase 20 | KGQuery `query_type="document"` — separate `_build_document_where_clause` + endpoint + client (§6.4) | ✅ Done |
| Phase 21 | Default vector provider → OpenAI `text-embedding-3-small` (1536d); segment budget → 1024 tokens; Wikipedia test docs + segmentation sanity script | ✅ Done |
| Phase 22 | Client typed response models for segmentation (segment trigger, status, config CRUD); `max_segment_tokens` default 512→1024 across all layers (server models, client endpoint, Pydantic request/response) | ✅ Done |
| Phase 23 | E2e segmentation test verified (9/9 pass). Fixed: `setdefault("error_code", 0)` for server responses missing envelope; idempotent index setup (delete-before-create); dimension assertion accepts 384 or 1536. Test uses inline climate article (3 paragraphs: ocean/coral, solar/wind, carbon capture), not Wikipedia docs. | ✅ Done |

### Future Items

| Item | Description | Notes |
|---|---|---|
| Fixed-token-window splitter | `urn:segmethod:fixed_token_window` — split by fixed token count with configurable overlap | New segmentation method; no phase assigned yet |
| Sentence-boundary splitter | `urn:segmethod:sentence_boundary` — split at sentence boundaries targeting a token budget | New segmentation method; no phase assigned yet |
| Retry sweep | Periodic re-enqueue of failed segmentation jobs with exponential backoff (`attempt_count < 3`, delay = `2^attempt * 1 min`) | Described in Background Segmentation design (§5) but not implemented as a separate phase |
| UI polling refinement | Detail/list page auto-poll for pending/in_progress jobs — stop polling once completed/failed | Partially covered by Phases 13–14; may need tuning (poll interval, backoff, WebSocket upgrade) |

### Architecture Implemented

```
Original KGDocument (never modified)
    │
    ├── Edge_hasKGDocumentSegment ──→ Parent Copy (segType=segmentation_parent)
    │                                      │
    │                                      ├── Edge_hasKGDocumentSegment ──→ Segment 1
    │                                      ├── Edge_hasKGDocumentSegment ──→ Segment 2
    │                                      └── Edge_hasKGDocumentSegment ──→ Segment N
    │
    └── (second method, if configured)
         └── Edge_hasKGDocumentSegment ──→ Parent Copy (different method)
                                                └── ...
```

**URI scheme** (deterministic):
- Parent: `{original_uri}_parent_{method_suffix}`
- Segments: `{parent_uri}_seg_{index}`
- Edges: `{original_uri}_edge_to_{method_suffix}_parent`, `{parent_uri}_edge_to_seg_{index}`

**Splitting algorithms**:
- **Markdown splitter** (`urn:segmethod:markdown_heading_split`): Splits at `#{1-3}` headings, recursively sub-splits oversized sections
- **Plain splitter** (`urn:segmethod:plain_recursive_split`): Splits at `\n\n` → `\n` → `. ` → ` ` → hard-chunk

**Content extraction priority**: `kGDocumentExtractedContent` → `kGDocumentHTMLContent` (strip HTML) → `kGDocumentContent`

**Auto-detection**: If ≥2 markdown heading patterns (`^#{1,6}\s`) found → markdown splitter, else plain splitter.

### Implemented: Dedicated KGDocument CRUD Endpoints

Following the same pattern as `KGTypesEndpoint` (and `KGEntitiesEndpoint`), full CRUD endpoints for KGDocument objects are now implemented:

#### REST API Routes

| Method | Path | Description |
|---|---|---|
| GET | `/api/graphs/kgdocuments` | List/search KGDocuments (paginated, filterable by type) |
| GET | `/api/graphs/kgdocuments?uri=...` | Get single KGDocument by URI (with quads) |
| POST | `/api/graphs/kgdocuments` | Create KGDocument(s) from quad payload |
| PUT | `/api/graphs/kgdocuments` | Update KGDocument(s) from quad payload |
| DELETE | `/api/graphs/kgdocuments` | Delete KGDocument(s) by URI/URI-list |
| POST | `/api/graphs/kgdocuments/segment` | Trigger segmentation (already implemented) |
| GET | `/api/graphs/kgdocuments/segments?parent_uri=...` | List segments for a given parent |

**Note**: Segmentation config CRUD and vector index/mapping management use the existing vector infrastructure endpoints:

| Existing Endpoint | Used For |
|---|---|
| `POST /api/vector-indexes?space_id=...` | Create `document_segments` index (same as any other index) |
| `GET/POST/PUT/DELETE /api/vector-mappings?space_id=...` | Map KGDocument segment type → `document_segments` index |

The `document_segments` vector index is just another entry in `{space}_vector_index` — it uses the same provider/model infrastructure as entity vectors. The `vector_index_setup.py` helper is a convenience for programmatic bootstrapping, but the UI manages it through the existing Vector Indexes and Vector Mappings pages.

#### Query Parameters (GET list)

| Param | Type | Description |
|---|---|---|
| `space_id` | string | Space ID (required) |
| `graph_id` | string | Graph ID (required) |
| `page_size` | int | Items per page (default 10, max 100) |
| `offset` | int | Pagination offset |
| `search` | string | Full-text search on name/headline/content |
| `document_type_uri` | string | Filter by kGDocumentType |
| `include_segments` | bool | Include segment children (default false) |
| `uri` | string | Get specific document by URI |

#### Implementation Files (New)

| File | Purpose |
|---|---|
| `vitalgraph/kg_impl/kgdocuments_create_impl.py` | Create processor (validate + store quads + auto-segment hook) |
| `vitalgraph/kg_impl/kgdocuments_read_impl.py` | Read processor (list, get by URI, get segments) |
| `vitalgraph/kg_impl/kgdocuments_update_impl.py` | Update processor (update quads + re-segment hook) |
| `vitalgraph/kg_impl/kgdocuments_delete_impl.py` | Delete processor (cascade delete: original + parent copies + segments) |
| `vitalgraph/endpoint/kgdocuments_endpoint.py` | REST endpoint (extend existing with CRUD routes) |
| `vitalgraph/model/kgdocuments_model.py` | Pydantic models (extend existing with CRUD request/response) |

#### CRUD Behavior

- **Create**: Store KGDocument quads → check segmentation config → if auto-segment enabled, call `AutoSegmentationHook.on_document_upsert()`
- **Update**: Replace quads → re-segment if content changed (SHA-256 content hash stored on completed jobs; `enqueue()` skips if hash matches latest completed job)
- **Delete**: Delete original document quads → cascade delete all parent copies + segments + edges (FILTER by URI prefix)
- **List**: SPARQL-backed query filtering on type, search text, segment exclusion by default
- **Get segments**: Given a parent/original URI, return segment list ordered by `kGDocumentSegmentIndex`

#### Quad-Level Detection (same pattern as KG Entities)

KGDocument creates/updates must also be detected at the **quad storage level** — not only via the dedicated `/api/graphs/kgdocuments` endpoint. When quads are stored through the generic objects endpoint (`sparql_sql_db_objects`) or via SPARQL UPDATE, the system should:

1. **Inspect changed quads for content-affecting predicates** — if a quad's predicate is one of:
   - `haley:hasKGDocumentContent`
   - `haley:hasKGDocumentExtractedContent`
   - `haley:hasKGDocumentHTMLContent`
   
   ...then the subject is a KGDocument whose segments may be stale.

2. **Trigger auto-segmentation hook** — same as if the dedicated endpoint was called
3. **Trigger vectorization** — if a vector mapping exists for the document type

**Existing pattern to follow**: `EntityGraphCache.collect_invalidation_targets()` in `vitalgraph/cache/entity_graph_cache.py` already scans SPARQL UPDATE ops (INSERT DATA, DELETE DATA, MODIFY, etc.) at the quad level. It inspects subject URIs and predicates (e.g. `hasKGGraphURI`) to determine which cached entity graphs to invalidate. The same approach applies here:

```python
# Predicates that affect document segmentation
_SEGMENTATION_PREDICATES = frozenset([
    "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentContent",
    "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentExtractedContent",
    "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentHTMLContent",
])

# In the quad-level hook (same spot as cache invalidation):
for quad in changed_quads:
    if quad.predicate in _SEGMENTATION_PREDICATES:
        # Subject URI is a KGDocument that needs re-segmentation
        schedule_resegmentation(subject_uri=quad.subject, space_id=..., graph_uri=...)
```

This ensures that bulk imports, SPARQL inserts, and generic quad operations all consistently trigger re-segmentation and vectorization — regardless of which endpoint writes the data.

**Integration point**: The `auto_sync.schedule_sync()` function (used by `kgentities_endpoint.py` and `kgframes_endpoint.py`) already handles the vectorization side. The KGDocument hook would add segmentation triggering alongside or prior to vectorization.

#### Write Protection for Parent Copies and Segments

Parent copies (`segmentTypeURI = urn:segtype:segmentation_parent`) and segments (`segmentTypeURI = urn:segtype:markdown_section | urn:segtype:text_chunk`) are **internally managed** and must not be modified by external operations. Any attempt to create, update, or delete these objects directly should be rejected.

**Enforcement points:**

1. **Dedicated KGDocuments endpoint** — On create/update, inspect incoming quads for `hasKGDocumentSegmentTypeURI`. If the value is a managed segment type (`segmentation_parent`, `markdown_section`, `text_chunk`), reject with HTTP 400: _"Cannot directly modify segmentation-managed documents. Update the original document instead."_

2. **Generic objects/quad endpoints** — Same check at the quad storage layer. If a SPARQL INSERT/UPDATE targets a subject whose `segmentTypeURI` is a managed type, reject or skip the write.

3. **Delete protection** — Segments and parent copies should only be deleted via:
   - Cascade when the original document is deleted
   - Re-segmentation (old segments cleared before new ones are created)
   - Never by direct user DELETE requests

**Detection logic:**
```python
_MANAGED_SEGMENT_TYPES = frozenset([
    "urn:segtype:segmentation_parent",
    "urn:segtype:markdown_section",
    "urn:segtype:text_chunk",
])

def is_managed_document(subject_uri: str, quads: List) -> bool:
    """Check if a subject is a managed segment/parent by its segmentTypeURI."""
    for quad in quads:
        if quad.subject == subject_uri:
            if quad.predicate == HAS_SEGMENT_TYPE and quad.object in _MANAGED_SEGMENT_TYPES:
                return True
    return False
```

Alternatively, since parent/segment URIs follow a deterministic pattern (`*_parent_*`, `*_seg_*`), a fast URI-pattern check can serve as a first-pass guard before querying existing triples.

#### Background Segmentation & Indexing

Segmentation and vector indexing of KGDocuments must **never block** the FastAPI request/response cycle. These are potentially expensive operations (tokenization, embedding generation) and should run asynchronously in the background.

**Design:**

1. **Fire-and-forget task scheduling** — After a document create/update returns 200 to the client, schedule segmentation + vectorization as a background `asyncio.Task` (same pattern as `auto_sync.schedule_sync()`).

2. **Task queue (PostgreSQL-backed)** — Use a PostgreSQL table as the durable job queue. PostgreSQL is already the primary datastore, so no new infrastructure is needed.
   - **Job table** (`segmentation_jobs`): columns `id`, `space_id`, `graph_id`, `document_uri`, `status` (pending/in_progress/completed/failed), `attempt_count`, `created_at`, `updated_at`, `error_message`
   - **Enqueue**: INSERT a row with `status = 'pending'` after the CRUD endpoint returns 200
   - **Dequeue**: Background worker loop polls with `SELECT ... FOR UPDATE SKIP LOCKED` to claim the next pending job (prevents duplicate processing across workers)
   - **NOTIFY/LISTEN** (implemented): `pg_notify('{space_id}_seg_jobs', job_id)` on enqueue wakes the worker instantly via dedicated asyncpg LISTEN connections; idle poll interval is 30s safety-net only
   - **Bounded concurrency**: Worker pool of N concurrent `asyncio.Task`s (e.g. 4) pulling from the queue

3. **Flow:**
   ```
   Client POST /kgdocuments → Store quads → Return 200 immediately
                                    │
                                    └──→ Background task:
                                           1. Fetch document content
                                           2. Segment (tokenize + split)
                                           3. Store parent copy + segments
                                           4. Generate embeddings
                                           5. Store vectors in {space}_vec_document_segments
   ```

4. **Status tracking (PostgreSQL-backed)** — The `segmentation_jobs` table is the single source of truth for status and retry counts. Expose via `GET /api/kgdocuments/segmentation-status`:
   - `?document_uri=...` — status for a single document
   - `?space_id=...` — summary counts across all documents in a space
   - Response fields: `status` (pending/in_progress/completed/failed), `attempt_count`, `created_at`, `updated_at`, `error_message`, `segment_count` (once completed)
   - Example query: `SELECT status, attempt_count, error_message, updated_at FROM segmentation_jobs WHERE document_uri = $1 ORDER BY created_at DESC LIMIT 1`

5. **Retry on failure** — On failure, the worker updates `status = 'failed'` and increments `attempt_count` in the `segmentation_jobs` row. A periodic sweep re-enqueues failed jobs with `attempt_count < 3` using exponential backoff (`updated_at + interval '1 minute' * 2^attempt_count < now()`).

6. **Concurrency control** (implemented) — `EntityLockManager` advisory locks per document URI in all three segmentation paths: background worker `_process_job`, sync fallback `_handle_segment_sync`, and `AutoSegmentationHook._run_segmentation`. Prevents concurrent segmentation of the same document across instances.

7. **UI integration** — Surface segmentation status on the KGDocument detail page and list page:
   - **Detail page**: Show a status badge (pending/in_progress/completed/failed) with attempt count. If failed, show the error message and a "Retry" button.
   - **List page**: Add a status column/icon per document (e.g. spinner for in_progress, check for completed, warning for failed).
   - **Polling**: The UI polls `/segmentation-status?document_uri=...` every few seconds while status is `pending` or `in_progress`, then stops.

This ensures the API remains fast (<50ms response) regardless of document size or embedding model latency.

#### Wiring into Server

1. **Register endpoint router** — Wire `KGDocumentsEndpoint(space_manager, auth_dep).router` into `VitalGraphAppImpl` under `/api/graphs` prefix (same as KGTypes)
2. **Vector index bootstrap (implemented)** — `setup_document_segments_vectorization(conn, space_id)` is called automatically during space creation in both `SparqlSQLSchema.create_space()` and `FusekiPostgreSQLDbImpl.create_space_data_tables()`. Falls back gracefully if pgvector is unavailable.
3. **Client library** — Add `kgdocuments_endpoint.py` to the Python client with CRUD + `segment_document()` methods

#### Frontend Integration

1. **KGDocuments list page** — Already done (`/objects/kgdocuments`)
2. **KGDocument detail page** — New page showing document properties, content preview, segments tree
3. **Segment viewer** — Inline display of segments with token count badges and content
4. **Trigger segmentation button** — On detail page, manual "Segment" action calling POST `/segment`
5. **Command palette** — KG Documents added to command palette search results (keywords: documents, segmentation, kgdocument, segments, content)
