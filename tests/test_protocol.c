/*
 * test_protocol.c - Tests de las tramas sobre sockets reales (make test).
 */
#include "../protocol.h"

#include <stdio.h>
#include <sys/socket.h>
#include <unistd.h>

static int failures = 0;

#define CHECK(cond)                                                       \
    do {                                                                  \
        if (!(cond)) {                                                    \
            printf("  FALLO %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
            failures++;                                                   \
        }                                                                 \
    } while (0)

/* Dos sockets conectados entre sí (como una conexión TCP, pero sin puertos). */
static void pair(int *a, int *b)
{
    int sv[2];
    socketpair(AF_UNIX, SOCK_STREAM, 0, sv);
    *a = sv[0];
    *b = sv[1];
}

static void test_roundtrip_all_types(void)
{
    int a, b, t;
    frame_t f;
    pair(&a, &b);
    for (t = 1; t <= MSG_TYPE_MAX; t++) {
        CHECK(send_frame(a, t, 7, -42) == 0);
        CHECK(recv_frame(b, &f) == 1);
        CHECK(f.type == t && f.src == 7 && f.arg == -42);
    }
    close(a);
    close(b);
}

static void test_byte_by_byte(void)
{
    /* Una trama que llega de byte en byte se reconstruye igual (read_full). */
    int a, b, c, d, i;
    char raw[FRAME_SIZE];
    frame_t f;
    pair(&a, &b);
    pair(&c, &d);
    CHECK(send_frame(a, MSG_UPDATE, 3, 99) == 0);
    CHECK(read_full(b, raw, FRAME_SIZE) == FRAME_SIZE); /* los bytes tal como viajan */
    for (i = 0; i < FRAME_SIZE; i++)
        CHECK(write(c, raw + i, 1) == 1);
    CHECK(recv_frame(d, &f) == 1);
    CHECK(f.type == MSG_UPDATE && f.src == 3 && f.arg == 99);
    close(a);
    close(b);
    close(c);
    close(d);
}

static void test_close_and_garbage(void)
{
    int a, b;
    frame_t f;
    int bad[3] = {0, 0, 0}; /* tipo 0: no existe */

    pair(&a, &b);
    close(a);
    CHECK(recv_frame(b, &f) == 0); /* cierre limpio */
    close(b);

    pair(&a, &b);
    CHECK(write(a, "abc", 3) == 3);
    close(a);
    CHECK(recv_frame(b, &f) == -1); /* cierre a mitad de trama */
    close(b);

    pair(&a, &b);
    CHECK(write(a, bad, FRAME_SIZE) == FRAME_SIZE);
    CHECK(recv_frame(b, &f) == -1); /* tipo desconocido */
    close(a);
    close(b);
}

int main(void)
{
    test_roundtrip_all_types();
    test_byte_by_byte();
    test_close_and_garbage();
    printf("test_protocol: %s (%d fallos)\n", failures ? "FALLO" : "OK", failures);
    return failures ? 1 : 0;
}
