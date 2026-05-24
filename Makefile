.PHONY: install doctor test lint fmt api ui live-test audit docker-build docker-run docker-stop docker-clean

install:
	just install

doctor:
	just doctor

test:
	just test

lint:
	just lint

fmt:
	just fmt

api:
	just api

ui:
	just ui

live-test:
	just live-test

audit:
	just audit

docker-build:
	just docker-build

docker-run:
	just docker-run

docker-stop:
	just docker-stop

docker-clean:
	just docker-clean
