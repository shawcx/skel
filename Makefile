.PHONY: all run test test-frontend test-docker

# the test venv if there is one, see README.md
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

NAME    ?= Slog
NS      ?= skunk
WITH    ?=
WITHOUT ?=

all:

run:
	./skel.py --force $(if $(NS),--namespace $(NS)) $(if $(WITH),--with $(WITH)) $(if $(WITHOUT),--without $(WITHOUT)) $(NAME)

test:
	$(PYTHON) test/smoke.py

test-frontend:
	$(PYTHON) test/frontend.py

test-docker:
	$(PYTHON) test/docker.py
