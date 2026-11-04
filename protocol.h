/*
* protocol.h - Tramas y sockets.
*/

#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <arpa/inet.h>              // Conversión de direcciones IP
#include <netinet/in.h>             // Estructuras y constantes de IPv4
#include <netinet/tcp.h>            // Opciones de TCP
#include <string.h>                 // Funciones para trabajar con memoria y cadenas
#include <sys/socket.h>             // Funciones y estructuras de sockets
#include <unistd.h>                 // read(), write(), close()

#define FRAME_SIZE 12               // Tamaño de una trama: 3 enteros de 4 bytes

enum {
    // operaciones sobre la variablesç
    MSG_READ = 1,                   // Solicitar lectura
    MSG_READ_REPLY,                 // Respuesta a una lectura
    MSG_UPDATE,                      // Actualizar una variable
    MSG_UPDATE_ACK,                 // Confirmación de la actualización
    MSG_READY,                      // Indicar que está preparado
    MSG_START,                      // Indicar el inicio
    MSG_LOCK,                       // Solicitar un bloqueo
    MSG_GRANT,                      // Aceptar el bloqueo
    MSG_UNLOCK,                     // Quitar el bloqueo
    MSG_DONE,                       // Indicar que ha terminado
    MSG_TYPE_MAX = MSG_DONE
};

typedef struct {
    int type;
    int src;
    int arg;
} frame_t;

/**
* Devuelve el nombre de un tipo de mensaje.
*
* @param type Tipo de mensaje.
* @return Nombre del mensaje o NULL si el tipo no existe.
*/
const char *msg_name(int type);

/**
* Envía una trama con el tipo, origen y argumento indicados.
*
* @param fd Descriptor del socket.
* @param type Tipo de mensaje.
* @param src Identificador del nodo que envía el mensaje.
* @param arg Argumento del mensaje.
* @return 0 si se envía correctamente, -1 si ocurre un error.
*/
int send_frame(int fd, int type, int src, int arg);

/**
* Recibe una trama y comprueba que el tipo de mensaje sea válido.
*
* @param fd Descriptor del socket.
* @param f Estructura donde se guardará la trama recibida.
* @return 1 si se recibe correctamente, 0 si se cierra la conexión,
*         -1 si ocurre un error o la trama no es válida.
*/
int recv_frame(int fd, frame_t *f);

/**
* Lee n bytes del descriptor indicado.
*
* @param fd Descriptor del socket.
* @param buf Buffer donde se almacenan los datos.
* @param n Número de bytes que se quieren leer.
* @return Número de bytes leídos o -1 si ocurre un error.
*/
int read_full(int fd, void *buf, int n);

/**
* Escribe n bytes en el descriptor indicado.
*
* @param fd Descriptor del socket.
* @param buf Buffer con los datos que se quieren enviar.
* @param n Número de bytes que se quieren escribir.
* @return Número de bytes escritos o -1 si ocurre un error.
*/
int write_full(int fd, const void *buf, int n);

/**
* Crea un socket TCP para escuchar conexiones.
*
* @param port Puerto en el que se escucharán las conexiones.
* @return Descriptor del socket o -1 si ocurre un error.
*/
int sock_listen(int port);

/**
* Crea un socket TCP y se conecta a la IP y puerto indicados.
*
* @param ip Dirección IP del servidor.
* @param port Puerto del servidor.
* @return Descriptor del socket o -1 si ocurre un error.
*/
int sock_connect(const char *ip, int port);

#endif