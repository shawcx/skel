.PHONY: all run test

NAME ?= Slog
NS   ?= skunk

all:

run:
	./skel.py --force $(if $(NS),--namespace $(NS)) $(NAME)

test:
	python3 test/smoke.py
