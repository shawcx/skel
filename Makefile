.PHONY: all run test test-frontend

NAME ?= Slog
NS   ?= skunk
WITH ?=

all:

run:
	./skel.py --force $(if $(NS),--namespace $(NS)) $(if $(WITH),--with $(WITH)) $(NAME)

test:
	python3 test/smoke.py

test-frontend:
	python3 test/frontend.py
