#include "board.h"

/* Original five-column uppercase glyphs. Each column uses bits 0..6, top first. */
static const uint8_t font[26][5] = {
    {126,9,9,9,126}, {127,73,73,73,54}, {62,65,65,65,34}, {127,65,65,34,28},
    {127,73,73,73,65}, {127,9,9,9,1}, {62,65,73,73,122}, {127,8,8,8,127},
    {0,65,127,65,0}, {32,64,65,63,1}, {127,8,20,34,65}, {127,64,64,64,64},
    {127,2,12,2,127}, {127,4,8,16,127}, {62,65,65,65,62}, {127,9,9,9,6},
    {62,65,81,33,94}, {127,9,25,41,70}, {38,73,73,73,50}, {1,1,127,1,1},
    {63,64,64,64,63}, {31,32,64,32,31}, {63,64,56,64,63}, {99,20,8,20,99},
    {3,4,120,4,3}, {97,81,73,69,67}
};

static const uint8_t digits[10][5]={
    {62,81,73,69,62},{0,66,127,64,0},{66,97,81,73,70},{33,65,69,75,49},
    {24,20,18,127,16},{39,69,69,69,57},{60,74,73,73,48},{1,113,9,5,3},
    {54,73,73,73,54},{6,73,73,41,30}
};
static unsigned column(uint8_t c,unsigned x)
{
    if (c>='a' && c<='z') c-='a'-'A';
    if (c>='A' && c<='Z') return font[c-'A'][x];
    if (c>='0' && c<='9') return digits[c-'0'][x];
    switch (c) {
    case ' ': return 0;
    case ':': return x==2 ? 36 : 0;
    case '.': return x==2 ? 64 : 0;
    case '-': return 8;
    case '/': return 32u>>x;
    case '%': return (32u>>x) | ((x==0 || x==4) ? 65 : 0);
    default: return x==0 || x==4 ? 127 : 65;
    }
}
/* Bounded UTF-8 label rendering: one fallback glyph per unsupported codepoint. */
static void draw_text(uint16_t *line,unsigned y,unsigned left,unsigned top,
                      unsigned width,unsigned height,unsigned scale,struct ur_text text)
{
    if (y<top || y>=top+height) return;
    unsigned row=0,x=0;
    for (unsigned i=0;i<text.len;i++) {
        uint8_t c=text.bytes[i];
        if ((c & 0xc0)==0x80) continue;
        if (c=='\n' || x+5*scale>width) {
            x=0; row+=9*scale;
            if (c=='\n') continue;
        }
        if (row>y-top) break;
        unsigned bit=(y-top-row)/scale;
        if (bit<7) {
            for (unsigned k=0;k<5;k++) {
                if (!(column(c,k)&(1u<<bit))) continue;
                for (unsigned j=0;j<scale;j++) line[left+x+k*scale+j]=0xffde;
            }
        }
        x+=6*scale;
    }
}
void ur_scanline(const struct ur_view *v,unsigned y,uint16_t line[DISPLAY_WIDTH])
{
    for (unsigned x=0;x<DISPLAY_WIDTH;x++) line[x]=0x08e4;
    draw_text(line,y,12,16,216,53,2,v->title);
    draw_text(line,y,12,79,216,89,2,v->body);
    draw_text(line,y,12,172,216,94,2,v->live);
    for (unsigned i=0;i<4;i++) {
        unsigned left=i*60+3;
        if (y==275 && v->soft[i].len)
            for (unsigned x=left;x<left+54;x++) line[x]=0x45d1;
        draw_text(line,y,left,282,54,36,1,v->soft[i]);
    }
}
