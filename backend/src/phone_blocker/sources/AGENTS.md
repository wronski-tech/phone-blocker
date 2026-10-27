# sources/AGENTS.md

Each module here imports one public register. The contract is the docstring of
`__init__.py`; per-source details are in `../../../../docs/data-sources.md`.

- A snapshot source's `iter_records` must yield **every** id the register currently lists,
  with `None` for entries to keep unchanged (fresh or failed to fetch). An id that is not
  yielded is deleted after a complete run.
- `source_id` must be stable across runs (a register id or URL, never a row number), or
  every run deletes and recreates the source.
- Use `fetch()` for HTTP (retries on network errors, 429, 5xx and unparseable bodies),
  `find_numbers()` from `..phone` for phone text and `shorten_name()` for long legal names.
- Respect the register: set `DEFAULT_DELAY` between requests, use the shared `USER_AGENT`,
  and prefer bulk files over per-entry requests.
- Do not import personal data the app does not need (people's names in the pharmacy
  export, individual doctors' practices).
- Keep field values within the column sizes in `models.py` (department and label: 200).
