#   make         -> ./server
#   make test    -> tests del protocolo
#   make clean
CC      = gcc
CFLAGS  = -std=c11 -O2 -Wall -Wextra -pedantic -D_POSIX_C_SOURCE=200809L
LDLIBS  = -pthread

all: server

server: server.c protocol.c protocol.h
	$(CC) $(CFLAGS) -o server server.c protocol.c $(LDLIBS)

test_protocol: tests/test_protocol.c protocol.c protocol.h
	$(CC) $(CFLAGS) -o test_protocol tests/test_protocol.c protocol.c $(LDLIBS)

test: test_protocol
	./test_protocol

clean:
	rm -f server test_protocol

.PHONY: all test clean
