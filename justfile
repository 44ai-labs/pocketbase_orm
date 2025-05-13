build:
    uv build

clear:
    rm -rf dist/*

publish: test clear build
    uv publish

test:
    uv run pytest -xvs tests/

format:
    uvx ruff check . --fix && uvx ruff format .

ruff-ci:
    uvx ruff check . && uvx ruff format --check .

set-secrets:
    #!/usr/bin/env sh
    if [ ! -f .env ]; then
        echo "Error: .env file not found"
        exit 1
    fi
    while IFS='=' read -r key value || [ -n "$key" ]; do
        if [ -n "$key" ] && [ "${key#\#}" = "$key" ]; then
            trimmed_value=$(echo "$value" | xargs)
            echo "Setting $key as a secret..."
            gh secret set "$key" --body="$trimmed_value"
        fi
    done < .env

# first installs deps needed for script
# sudo apt install curl unzip
install-pocketbase:
	./scripts/install-pocketbase.sh

clear-pocketbase:
	rm -rf db/pb_data
	rm -rf db/pb_migrations

seed-pocketbase:
	ADMIN_EMAIL=admin@pb.com ADMIN_PASSWORD=mamaistdiebeste ./scripts/seed-pocketbase.sh

start-pocketbase:
	./db/pocketbase serve --dir=./db/pb_data --migrationsDir=./db/pb_migrations --http 127.0.0.1:4419

reset-pocketbase: clear-pocketbase seed-pocketbase start-pocketbase