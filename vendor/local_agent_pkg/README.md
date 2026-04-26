# proton-vpn-local-agent (maturin wrapper)

Empty-by-design Python project that delegates the build to maturin against the
Rust crate in `vendor/local-agent-rs/python-proton-vpn-local-agent/`.

uv pulls this directory in via `[tool.uv.sources]` in the parent `pyproject.toml`.
Don't reference it directly.
