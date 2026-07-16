# CP-3a core stack (core + Postgres + runner; see core/README.md).

stack-up:    ## build + start the local job-protocol stack
	docker compose up -d --build

stack-demo:  ## enqueue the no-credentials demo jobs and await results
	docker compose exec core sh -c 'node dist/cli.js enqueue --wait jobs/demo/*.json'

stack-live:  ## live overlay stack up + enqueue the example estate's three systems
	docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d --build
	docker compose exec core sh -c 'node dist/cli.js enqueue --wait jobs/live/*.json'

stack-down:  ## stop the stack (keeps the pgdata volume; add -v yourself to wipe)
	docker compose down

.PHONY: stack-up stack-demo stack-live stack-down
