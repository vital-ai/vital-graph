-- Deterministic UUID v5 function for RDF term identifiers.
-- Mirrors Python's _generate_term_uuid() exactly, including \x00 separators.
-- Requires: pgcrypto extension (for digest()).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION vitalgraph_term_uuid(
    p_text text, p_type char(1),
    p_lang text DEFAULT NULL,
    p_datatype_id bigint DEFAULT NULL
) RETURNS uuid AS $$
DECLARE
    name_bytes bytea;
    ns_bytes bytea;
    hash bytea;
    raw bytea;
BEGIN
    -- Build name: text \x00 type [\x00 lang:X] [\x00 datatype:N]
    name_bytes := convert_to(p_text, 'UTF8') || '\x00'::bytea || convert_to(p_type, 'UTF8');
    IF p_lang IS NOT NULL THEN
        name_bytes := name_bytes || '\x00'::bytea || convert_to('lang:' || p_lang, 'UTF8');
    END IF;
    IF p_datatype_id IS NOT NULL THEN
        name_bytes := name_bytes || '\x00'::bytea || convert_to('datatype:' || p_datatype_id::text, 'UTF8');
    END IF;

    -- UUID v5 namespace bytes (6ba7b810-9dad-11d1-80b4-00c04fd430c8)
    ns_bytes := '\x6ba7b8109dad11d180b400c04fd430c8'::bytea;

    -- SHA-1(namespace || name)
    hash := digest(ns_bytes || name_bytes, 'sha1');

    -- Take first 16 bytes, set version=5 (byte 6) and variant=2 (byte 8)
    raw := substring(hash from 1 for 16);
    raw := set_byte(raw, 6, (get_byte(raw, 6) & 15) | 80);   -- version 5
    raw := set_byte(raw, 8, (get_byte(raw, 8) & 63) | 128);  -- variant 2

    RETURN encode(raw, 'hex')::uuid;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
