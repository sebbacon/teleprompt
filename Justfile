build:
    uv run python3 build_teleprompter.py

serve:
    uv run python3 build_teleprompter.py serve

build-and-serve: build serve
