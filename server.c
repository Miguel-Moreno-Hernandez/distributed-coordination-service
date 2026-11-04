#include "protocol.h"

#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define MAX_SERVERS 128                                         // Número máximo de servidores

static int my_id = -1;                                          // ID de este servidor
static int n_servers = 0;                                       // Número total de servidores
static int rw = -1;                                             // 1 = lee y escribe, 0 = solo lee
static int iterations = 10;                                     // Número de iteraciones
static double sleep_s = 1.0;                                    // Tiempo de espera entre iteraciones del enunciado = 1000 ms
static int wait_key = 1;                                        // Esperar ENTER antes de empezar
static const char *coord_ip = "127.0.0.1";                      // IP del coordinador
static int port = 5000;                                         // Puerto del coordinador
static FILE *log_fp;                                            // Archivo de logs

// estado compartido entre hilos (protegido por mutex)
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;          // Protege el estado compartido
static pthread_cond_t cv = PTHREAD_COND_INITIALIZER;            // Coordina los hilos

static int value = 0;                                           // Valor de la variable compartida
static int next_ticket = 0;                                     // Siguiente número de turno
static int now_serving = 0;                                     // Turno que se está atendiendo
static int holder = -1;                                         // Servidor que tiene el bloqueo
static int n_ready = 0;                                         // Servidores que están preparados
static int n_done = 0;                                          // Servidores que han terminado
static int joined[MAX_SERVERS];                                 // Indica qué servidores ya están conectados
static int sent[MSG_TYPE_MAX + 1];                              // Número de mensajes enviados por tipo

// Devuelve el tiempo actual en nanosegundos para que los logs sean exactos
static long long now_ns(void) {
    struct timespec ts;

    clock_gettime(CLOCK_MONOTONIC, &ts);

    return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

// Registra un evento
static void log_event(const char *event, const char *extra) {
    static pthread_mutex_t log_mu = PTHREAD_MUTEX_INITIALIZER;

    pthread_mutex_lock(&log_mu);

    fprintf(log_fp, "{\"t\": %lld, \"node\": %d, \"event\": \"%s\"%s%s}\n", now_ns(), my_id, event, extra != NULL ? ", " : "", extra != NULL ? extra : "");

    fflush(log_fp);

    pthread_mutex_unlock(&log_mu);
}

/* Muestra un error, lo registra y termina el servidor */
static void die(const char *text) {
    printf("[servidor %d] ABORTADO: %s\n", my_id, text);
    fflush(stdout);

    char extra[512];

    snprintf(extra, sizeof(extra), "\"reason\": \"%s\"", text);
    log_event("failure", extra);

    _exit(1); // termina todos los hilos. No uso exit normal para que los demas tamabien se cierren de forma inmediata
}

// Envía un mensaje y se carga el servidor si falla
static void send_or_die(int fd, int type, int arg) {

    char text[256];

    pthread_mutex_lock(&mu);

    sent[type]++;

    pthread_mutex_unlock(&mu);

    if (send_frame(fd, type, my_id, arg) != 0) {
        snprintf(text, sizeof(text), "no se pudo enviar %s", msg_name(type));
        die(text);
    } 
}

// Espera el tiempo indicado en segundos
static void sleep_seconds(double s) {

    struct timespec ts;

    ts.tv_sec = (int)s;
    ts.tv_nsec = (long)((s - ts.tv_sec) * 1e9);     // 1e9 = 1.000.000.000 en notación científica

    nanosleep(&ts, NULL);
}

// Espera a que el usuario pulse ENTER
static void wait_for_enter(void) {

    int c;

    if (!wait_key) {
        return;
    }

    printf("[servidor %d] listo. Pulsa ENTER cuando todos los servidores estén arrancados...", my_id);
    fflush(stdout);

    while ((c = getchar()) != '\n' && c != EOF) {

    }
}

/* COORDINADOR (servidor 0) */

// Adquiere el bloqueo siguiendo el orden de llegada
static void lock_acquire(int who) {

    int my_ticket;

    pthread_mutex_lock(&mu);
    my_ticket = next_ticket++;

    while (now_serving != my_ticket) {
        pthread_cond_wait(&cv, &mu);    // un hilo espera hasta que se produzca un cambio en una condición, asi no gasta cpu todo el rato´ç
    }

    holder = who;
    pthread_mutex_unlock(&mu);
}

// Libera el bloqueo y pasa el turno al siguiente servidor
static void lock_release(int who) {

    pthread_mutex_lock(&mu);

    if (holder != who) {
        char text[256];

        snprintf(text, sizeof(text), "el servidor %d ha soltado un cerrojo que no tenía", who);

        die(text);
    }

    holder = -1;
    now_serving++;

    pthread_cond_broadcast(&cv);
    pthread_mutex_unlock(&mu);
}

// Espera a que todos los servidores estén preparados
static void barrier(void) {

    pthread_mutex_lock(&mu);

    n_ready++;

    pthread_cond_broadcast(&cv);

    while (n_ready < n_servers) {
        pthread_cond_wait(&cv, &mu);
    }

    pthread_mutex_unlock(&mu);
}

// Atiende las peticiones de un servidor conectado
static void *serve_client(void *arg) {

    int fd = (int)(long)arg;
    int id = -1, done = 0, r, v;

    char text[256];

    frame_t f;

    while ((r = recv_frame(fd, &f)) == 1) {

        if (id < 0) {
            // Comprueba que la primera trama sea un READY válido y que el servidor no esté conectado.
            int ok = f.type == MSG_READY && f.src > 0 && f.src < n_servers;

            pthread_mutex_lock(&mu);

            if (ok && !joined[f.src]) {
                joined[f.src] = 1;
            } 
            else {
                ok = 0;
            }

            pthread_mutex_unlock(&mu);

            if (!ok) {
                close(fd);
                return NULL;
            }

            id = f.src;
        } 
        else {
            if (f.src != id) {
                snprintf(text, sizeof(text),
                        "trama con un origen (%d) distinto al de su conexión", f.src);
                die(text);
            }
        }

        switch (f.type) {

            case MSG_READY:
                barrier();
                send_or_die(fd, MSG_START, 0);
                break;

            case MSG_LOCK:
                lock_acquire(id);
                send_or_die(fd, MSG_GRANT, 0);
                break;

            case MSG_UNLOCK:
                lock_release(id);
                break;

            case MSG_READ:
                pthread_mutex_lock(&mu);

                v = value;

                pthread_mutex_unlock(&mu);
                send_or_die(fd, MSG_READ_REPLY, v);
                break;

            case MSG_UPDATE:
                pthread_mutex_lock(&mu);

                if (holder != id) {
                    snprintf(text, sizeof(text),
                            "UPDATE del servidor %d sin tener el cerrojo", id);
                    die(text);
                }
                    
                value = f.arg; // Guardo antes de confirmar

                pthread_mutex_unlock(&mu);
                send_or_die(fd, MSG_UPDATE_ACK, 0);
                break;

            case MSG_DONE:
                done = 1;
                pthread_mutex_lock(&mu);

                n_done++;
                
                pthread_cond_broadcast(&cv);
                pthread_mutex_unlock(&mu);
                break;

            default:
                snprintf(text, sizeof(text),
                        "trama %s inesperada del servidor %d",
                        msg_name(f.type), id);
                die(text);
        }
    }

    if (id >= 0 && !done) {
        snprintf(text, sizeof(text), "el servidor %d se ha desconectado sin terminar", id);
        die(text);
    }

    close(fd);

    return NULL;
}

// Espera conexiones y crea un hilo para atender cada servidor
static void *accept_loop(void *arg) {

    int listen_fd = (int)(long)arg;

    for (;;) {

        pthread_t t;
        int yes = 1;
        int fd = accept(listen_fd, NULL, NULL);

        if (fd < 0) {
            continue;
        }

        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes)); // las respuestas salen en el instant
        
        if (pthread_create(&t, NULL, serve_client, (void *)(long)fd) != 0) {
            close(fd);
            continue;
        }
        pthread_detach(t);
    }
    return NULL;
}

// Ejecuta el servidor coordinador y controla las iteraciones
static void run_coordinator(void) {

    pthread_t t;

    int i, v, final_value;
    int listen_fd = sock_listen(port);

    char text[256];
    char extra[512];

    if (listen_fd < 0) {
        snprintf(text, sizeof(text), "no se pudo escuchar en el puerto %d (¿ocupado?)", port);
        die(text);
    }
        
    if (pthread_create(&t, NULL, accept_loop, (void *)(long)listen_fd) != 0) {
        die("no se pudo crear el hilo que acepta conexiones");
    }
 
    log_event("connected", NULL);

    wait_for_enter();
    barrier();
    log_event("start", NULL);

    for (i = 0; i < iterations; i++) {

        log_event("request_cs", NULL);
        lock_acquire(0);
        log_event("enter_cs", NULL);
        pthread_mutex_lock(&mu);

        v = value;                    // Lee el valor compartido

        pthread_mutex_unlock(&mu);
        
        snprintf(extra, sizeof(extra), "\"value\": %d", v);
        log_event("read", extra);

        if (rw) {
            pthread_mutex_lock(&mu);
            value = v + 1;            // Incrementa el valor compartido
            pthread_mutex_unlock(&mu);
            
            snprintf(extra, sizeof(extra), "\"value\": %d", v + 1);
            log_event("update", extra);
        }

        log_event("exit_cs", NULL);
        lock_release(0);

        if (rw) {
            printf("[servidor 0 rw] iteración %d: leído %d, escrito %d\n", i, v, v + 1);
        }
        else {
            printf("[servidor 0 ro] iteración %d: leído %d\n", i, v);
        }

        fflush(stdout);
        sleep_seconds(sleep_s);
    }

    // No se puede cerrar hasta que todos hayan terminado, por eso guardo la variable
    pthread_mutex_lock(&mu);

    while (n_done < n_servers - 1) {
        pthread_cond_wait(&cv, &mu);        
    }

    final_value = value;
    pthread_mutex_unlock(&mu);
    
    snprintf(extra, sizeof(extra), "\"final_value\": %d, \"sent\": {\"START\": %d, \"GRANT\": %d, " "\"READ_REPLY\": %d, \"UPDATE_ACK\": %d}", final_value, sent[MSG_START], sent[MSG_GRANT], sent[MSG_READ_REPLY], sent[MSG_UPDATE_ACK]);

    log_event("finished", extra);

    printf("[servidor 0] todos han terminado. Valor final = %d\n", final_value);
}

/*  SERVIDOR NORMAL (1..N-1 [maximo 128]) */

// Espera una respuesta del coordinador y comprueba su tipo
static int expect(int fd, int type) {

    char text[256];

    frame_t f;

    if (recv_frame(fd, &f) != 1) {
        die("se ha perdido la conexión con el coordinador");
    }
    if (f.type != type) {
        snprintf(text, sizeof(text),"se esperaba %s y ha llegado %s",msg_name(type), msg_name(f.type));
        die(text);
    }
    
    return f.arg;
}

// Conecta con el coordinador y ejecuta las iteraciones del servidor
static void run_client(void) {
    int fd, i, v, tries = 0;

    char text[256];
    char extra[512];

    // Espera a que todos estén listos antes de conectarse y enviar READY
    wait_for_enter();
    
    // Intenta conectarse al coordinador durante un máximo de 60 segundos
    while ((fd = sock_connect(coord_ip, port)) < 0) {

        if (++tries > 300) {
            snprintf(text, sizeof(text),"no se pudo conectar con el coordinador %s:%d", coord_ip, port);
            die(text);
        }

        sleep_seconds(0.2);
    }

    log_event("connected", NULL);
    send_or_die(fd, MSG_READY, 0);
    expect(fd, MSG_START);
    log_event("start", NULL);

    for (i = 0; i < iterations; i++) {

        log_event("request_cs", NULL);
        send_or_die(fd, MSG_LOCK, 0);
        expect(fd, MSG_GRANT);
        log_event("enter_cs", NULL);

        send_or_die(fd, MSG_READ, 0);
        v = expect(fd, MSG_READ_REPLY);                             // Lee el valor compartido
        
        snprintf(extra, sizeof(extra), "\"value\": %d", v);
        log_event("read", extra);
        
        if (rw) {
            send_or_die(fd, MSG_UPDATE, v + 1);                     // Actualiza el valor compartido
            expect(fd, MSG_UPDATE_ACK);
            
            snprintf(extra, sizeof(extra), "\"value\": %d", v + 1);
            log_event("update", extra);
        }

        log_event("exit_cs", NULL);                                 // Registra la salida de la sección crítica antes de liberar el bloqueo
        send_or_die(fd, MSG_UNLOCK, 0);

        if (rw) {
                printf("[servidor %d rw] iteración %d: leído %d, escrito %d\n", my_id, i, v, v + 1);
        }
        else {
            printf("[servidor %d ro] iteración %d: leído %d\n", my_id, i, v);
        }

        fflush(stdout);
        sleep_seconds(sleep_s);
    }

    send_or_die(fd, MSG_DONE, 0);
    
    snprintf(extra, sizeof(extra), "\"sent\": {\"READY\": %d, \"LOCK\": %d, \"READ\": %d, " "\"UPDATE\": %d, \"UNLOCK\": %d, \"DONE\": %d}", sent[MSG_READY], sent[MSG_LOCK], sent[MSG_READ], sent[MSG_UPDATE], sent[MSG_UNLOCK], sent[MSG_DONE]);

    log_event("finished", extra);

    printf("[servidor %d] terminado\n", my_id);
    close(fd);
}

/* main */

// Convierte un texto a número y comprueba que esté dentro del rango indicado
static int to_number(const char *s, double min, double max, double *out) {
    char *end;
    double v = strtod(s, &end);

    if (end == s || *end != '\0' || !(v >= min && v <= max)) {
        return 0;
    }

    *out = v;

    return 1;
}

int main(int argc, char **argv) {

    const char *mode = NULL, *log_dir = "logs";

    char extra[512];
    char path[512];

    double num;
    int i;

    for (i = 1; i < argc; i++) {

        const char *a = argv[i];
        const char *v = i + 1 < argc ? argv[i + 1] : "";

        if (strcmp(a, "--no-wait") == 0) {
            wait_key = 0;
            continue;
        }

        if (strcmp(a, "--id") == 0 && to_number(v, 0, MAX_SERVERS - 1, &num) && num == (int)num) {
            my_id = (int)num;
        }
        else {
            if (strcmp(a, "--n") == 0 && to_number(v, 1, MAX_SERVERS, &num) && num == (int)num) {
                n_servers = (int)num;
            }
            else {
                if (strcmp(a, "--mode") == 0 && (strcmp(v, "rw") == 0 || strcmp(v, "ro") == 0)) {
                    mode = v;
                }
                else {
                    if (strcmp(a, "--ip") == 0 && v[0] != '\0') {
                        coord_ip = v;
                    }
                    else {
                        if (strcmp(a, "--port") == 0 && to_number(v, 1, 65535, &num) && num == (int)num) {
                            port = (int)num;
                        }
                        else {
                            if (strcmp(a, "--sleep") == 0 && to_number(v, 0, 3600, &num)) {
                                sleep_s = num;
                            }
                            else {
                                if (strcmp(a, "--iterations") == 0 && to_number(v, 0, 100000, &num) && num == (int)num) {
                                    iterations = (int)num;
                                }
                                else {
                                    if (strcmp(a, "--log-dir") == 0 && v[0] != '\0') {
                                        log_dir = v;
                                    }
                                    else {
                                        fprintf(stderr, "argumento inválido: %s %s\n", a, v);

                                        fprintf(stderr,
                                                "uso: ./server --id ID --mode rw|ro --n N [--ip 127.0.0.1] [--port 5000]\n"
                                                "     [--sleep 1] [--iterations 10] [--no-wait] [--log-dir logs]\n"
                                                "  El servidor 0 es el coordinador; los demás se conectan a --ip:--port.\n");

                                        exit(2);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        i++;
    }

    if (my_id < 0 || n_servers < 1 || my_id >= n_servers || mode == NULL) {
        fprintf(stderr,
                "uso: ./server --id ID --mode rw|ro --n N [--ip 127.0.0.1] [--port 5000]\n"
                "     [--sleep 1] [--iterations 10] [--no-wait] [--log-dir logs]\n"
                "  El servidor 0 es el coordinador; los demás se conectan a --ip:--port.\n");
        exit(2);
    }

    rw = strcmp(mode, "rw") == 0;

    signal(SIGPIPE, SIG_IGN); /* escribir en un socket cerrado da error en vez de matar el proceso */
    
    mkdir(log_dir, 0755);     /* si ya existe, da igual */
    snprintf(path, sizeof(path), "%s/node_%d.jsonl", log_dir, my_id);

    log_fp = fopen(path, "w");

    if (log_fp == NULL) {
        fprintf(stderr, "no se pudo crear %s\n", path);
        return 2;
    }
    
    snprintf(extra, sizeof(extra), "\"mode\": \"%s\", \"n\": %d, \"sleep\": %g, \"iterations\": %d", mode, n_servers, sleep_s, iterations);

    log_event("init", extra);

    if (my_id == 0) {
        run_coordinator(); 
    }
    else {
        run_client();
    }

    return 0;
}