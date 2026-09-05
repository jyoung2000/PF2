"""Film Studio (Phase S): persistent visual assets with immutable versions and
locks, story → scenes → shots with inheritance, AI Director proposals, takes
through the existing generation queue, timeline/export. Everything here
reuses PF2's storage (DATA_DIR/film), settings, LLM client, provider
router/pricing and media tooling — no second subsystem."""
