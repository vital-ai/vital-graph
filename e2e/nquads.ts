/**
 * Decode the N-Quads-encoded terms the quad APIs return.
 *
 * Every endpoint that answers with `results: [{s, p, o}]` returns N-Quads
 * strings, not bare values: `<uri>`, `"lexical"`, `"lexical"^^<datatype>`,
 * `"lexical"@lang`, `_:label`.
 *
 * Tests used to strip these with `.replace(/^"|"$/g, '')`, which handles only
 * the untyped `"lexical"` form. That stopped being enough: the encoder now
 * writes the datatype for EVERY literal, including `xsd:string`, deliberately
 * — `quad_format_utils.rdflib_term_to_nquads` records why (`issues/221`,
 * `issues/234`: a quad's term uuid hashes the datatype id, so the elided form
 * is a different term from the one every other producer writes). A quote-only
 * strip leaves `^^<http://www.w3.org/2001/XMLSchema#string>` on the value,
 * which fails an equality assertion and — worse — silently matches nothing in
 * the cleanup helpers that compare a name to find what to delete.
 *
 * Use `termValue` wherever a quad's value is compared to a plain string.
 */

/** Inverse of `_escape_nquads_string`, plus the `\t` the grammar allows. */
const UNESCAPE: Record<string, string> = {
  '\\': '\\',
  '"': '"',
  n: '\n',
  r: '\r',
  t: '\t',
};

// Greedy lexical capture, then an OPTIONAL datatype or language suffix. Greedy
// plus the `$` anchor is what makes an embedded escaped quote safe: the regex
// backtracks to the last quote that is followed only by a suffix.
const LITERAL = /^"([\s\S]*)"(?:\^\^<[^>]*>|@[A-Za-z0-9-]+)?$/;

/**
 * The plain value of an N-Quads term: URI without brackets, literal without
 * quotes, datatype, language tag or backslash escapes. Anything unrecognised
 * (a blank node, an already-plain string) is returned unchanged.
 */
export function termValue(term: unknown): string {
  const raw = String(term ?? '');

  if (raw.startsWith('<') && raw.endsWith('>')) {
    return raw.slice(1, -1);
  }

  const m = LITERAL.exec(raw);
  if (!m) return raw;

  return m[1].replace(/\\([\s\S])/g, (whole, ch) =>
    ch in UNESCAPE ? UNESCAPE[ch] : whole,
  );
}

/** The datatype URI of an N-Quads literal, or '' when it carries none. */
export function termDatatype(term: unknown): string {
  const m = /\^\^<([^>]*)>$/.exec(String(term ?? ''));
  return m ? m[1] : '';
}
