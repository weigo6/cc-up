"""SQL port of CC-Switch 27e2cffa (MIT); see THIRD_PARTY_NOTICES.md.

Only read-time rules are used here. Agent session files are never opened.
"""

RULE_VERSION = "cc-switch-27e2cffa-v1"
INCLUSIVE_APPS = "'codex', 'gemini', 'grokbuild'"


def fresh_input(alias: str) -> str:
    return f"""CASE
      WHEN {alias}.input_token_semantics = 2 THEN {alias}.input_tokens
      WHEN {alias}.app_type IN ({INCLUSIVE_APPS}) AND {alias}.input_token_semantics = 1
        AND {alias}.input_tokens >= {alias}.cache_read_tokens + {alias}.cache_creation_tokens
        THEN {alias}.input_tokens - {alias}.cache_read_tokens - {alias}.cache_creation_tokens
      WHEN {alias}.app_type IN ({INCLUSIVE_APPS}) AND {alias}.input_token_semantics = 0
        AND {alias}.input_tokens >= {alias}.cache_read_tokens
        THEN {alias}.input_tokens - {alias}.cache_read_tokens
      ELSE {alias}.input_tokens END"""


def effective_filter(alias: str = "l") -> str:
    source = f"COALESCE({alias}.data_source, 'proxy')"
    return f"""NOT (
      {source} IN ('session_log','codex_session','gemini_session','opencode_session')
      AND EXISTS (SELECT 1 FROM proxy_request_logs p
        WHERE COALESCE(p.data_source,'proxy') = 'proxy'
          AND p.app_type IN ({alias}.app_type,
              CASE WHEN {alias}.app_type = 'claude' THEN 'claude-desktop' ELSE {alias}.app_type END)
          AND p.status_code >= 200 AND p.status_code < 300
          AND p.input_tokens = {alias}.input_tokens
          AND p.output_tokens = {alias}.output_tokens
          AND p.cache_read_tokens = {alias}.cache_read_tokens
          AND (p.cache_creation_tokens = {alias}.cache_creation_tokens
            OR ({alias}.cache_creation_tokens = 0
              AND {source} IN ('codex_session','gemini_session','opencode_session'))
            OR (p.cache_creation_tokens = 0 AND p.input_token_semantics = 0
              AND {source} = 'codex_session'))
          AND p.created_at BETWEEN {alias}.created_at - 600 AND {alias}.created_at + 600
          AND (LOWER(p.model) = LOWER({alias}.model)
            OR LOWER(p.model) = 'unknown' OR LOWER({alias}.model) = 'unknown'
            OR ({alias}.app_type = 'codex' AND {source} = 'codex_session'
              AND NULLIF(TRIM(p.request_model),'') IS NOT NULL
              AND LOWER(TRIM(p.request_model)) <> 'unknown'
              AND LOWER(TRIM(p.request_model)) = LOWER(TRIM({alias}.model))))
      ))"""
