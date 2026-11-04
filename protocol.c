/*
 * protocol.c - Tramas de 3 enteros y sockets TCP.
 */
#include "protocol.h"

// Tipos de mensajes que pueden intercambiar los nodos
const char *NAMES[MSG_TYPE_MAX + 1] = {
    NULL,
    "READ",
    "READ_REPLY",
    "UPDATE",
    "UPDATE_ACK",
    "READY",
    "START",
    "LOCK",
    "GRANT",
    "UNLOCK",
    "DONE"
};

// Devuelve el nombre de un tipo de mensaje
const char *msg_name(int type) {
    if (type < 1 || type > MSG_TYPE_MAX) {
        return NULL;
    }

    return NAMES[type];
}

// Lee hasta recibir n bytes o hasta que se cierre la conexión
int read_full(int fd, void *buf, int n) {

    char *p = buf;
    int got = 0;

    while (got < n) {

        int r = read(fd, p + got, n - got);

        if (r == 0) {
            break; // Se ha cerrado el otro lado
        }
            
        if (r < 0){
            return -1;
        }
        
        got += r;
    }
    return got;
}

// Escribe todos los bytes del buffer
int write_full(int fd, const void *buf, int n) {
    
    const char *p = buf;
    int sent = 0;

    while (sent < n) {
        int w = write(fd, p + sent, n - sent);

        if (w <= 0) {
            return -1;
        }
        sent += w;
    }
    return sent;
}

// Envía un mensaje con su tipo, origen y argumento
int send_frame(int fd, int type, int src, int arg) {
    int buf[3];

    buf[0] = htonl(type);
    buf[1] = htonl(src);
    buf[2] = htonl(arg);

    return write_full(fd, buf, FRAME_SIZE) == FRAME_SIZE ? 0 : -1;
}

// Recibe una trama y comprueba que el tipo de mensaje sea válido
int recv_frame(int fd, frame_t *f) {

    int buf[3];
    int got = read_full(fd, buf, FRAME_SIZE);

    if (got == 0) {
        return 0; // cierre limpio, entre dos tramas
    }
        
    if (got != FRAME_SIZE) {
        return -1; // error o cierre a se ha cerrado a mitad de trama
    }
        
    // Aqui se convierten los datos recibidos a formato local
    f->type = ntohl(buf[0]);
    f->src = ntohl(buf[1]);
    f->arg = ntohl(buf[2]);

    if (msg_name(f->type) == NULL) {
        return -1;
    }

    return 1;
}

// Crea un socket para escuchar conexiones en el puerto indicado
int sock_listen(int port) {

    struct sockaddr_in addr;

    int yes = 1;
    int fd = socket(AF_INET, SOCK_STREAM, 0);

    if (fd < 0) {
        return -1;
    }
    
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes)); // puerto libre aunque quede en TIME_WAIT

    memset(&addr, 0, sizeof(addr));

    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = INADDR_ANY;

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0 || listen(fd, 128) < 0) {
        close(fd);
        return -1;
    }

    return fd;
}

// Crea un socket y se conecta a la IP y puerto indicados
int sock_connect(const char *ip, int port) {

    struct sockaddr_in addr;
    int yes = 1;
    int fd = socket(AF_INET, SOCK_STREAM, 0);

    if (fd < 0) {
        return -1;
    } 

    memset(&addr, 0, sizeof(addr));

    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);

    if (inet_pton(AF_INET, ip, &addr.sin_addr) != 1 || connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) { // Convierte la IP y conecta con el servidor
        close(fd);
        return -1;
    }

    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes)); // cada trama sale en el acto

    return fd;
}
