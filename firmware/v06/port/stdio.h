/* Only declarations consumed by this embedded SDK build. ROM provides printf. */
#include <stddef.h>
#define printf __2printf
int printf(const char *, ...);
int sprintf(char *, const char *, ...);
