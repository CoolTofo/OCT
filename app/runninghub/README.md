# RunningHub module

This package holds RunningHub-specific code that used to live directly in
`main.py`.

## Files

- `schemas.py`: Pydantic request and field models used by FastAPI routes.
- `client.py`: RunningHub base URL, API/upload URL selection, and HTTP headers.
- `fields.py`: Pure field normalization, type coercion, switch helpers, and video
  loader field cleanup.
- `responses.py`: RunningHub task status, error text, JSON fallback, and result
  item extraction.
- `service.py`: A stable facade for route code. New RunningHub business logic
  should be exposed here first, then delegated to smaller modules underneath.
- `storage.py`: Saved workflow template JSON persistence.

## Direction

Keep `main.py` as the route/composition layer. When adding RunningHub features,
prefer one of these modules or a new file in this package instead of adding more
business logic to `main.py`.
