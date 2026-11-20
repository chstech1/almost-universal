#include "remote.h"

struct menu_bank {
    uint8_t data[UR_LIMIT], revision[8];
    uint16_t offsets[UR_SCREENS], home, count;
};
static struct menu_bank banks[2];
static unsigned selected_bank;
static uint16_t screen, expected, received, live_length;
static uint8_t live_text[255];
static bool active;
static ur_save_fn save_menu;
/* A held key keeps the source screen of its press, across local navigation. */
static uint16_t press_source[UR_CONTROLS];
static bool announced[UR_CONTROLS];

static uint16_t word(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static void copy(uint8_t *to, const uint8_t *from, size_t n)
{
    for (size_t i = 0; i < n; i++) to[i] = from[i];
}
static bool same_revision(const uint8_t *a, const uint8_t *b)
{
    for (unsigned i = 0; i < 8; i++) if (a[i] != b[i]) return false;
    return true;
}
static bool valid_menu(struct menu_bank *bank, size_t size)
{
    const uint8_t *p = bank->data;
    if (size < 8 || p[0]!='U' || p[1]!='R' || p[2]!='M' || p[3]!='1') return false;
    bank->count = word(p+4);
    bank->home = word(p+6);
    if (!bank->count || bank->count > UR_SCREENS || !bank->home || bank->home > bank->count)
        return false;
    size_t pos=8;
    for (unsigned s=0; s<bank->count; s++) {
        bank->offsets[s] = (uint16_t)pos;
        for (unsigned f=0; f<6; f++) {
            if (pos == size) return false;
            unsigned n=p[pos++];
            if (n > size-pos || (!f && (!n || n>64)) || (f>=2 && n>32)) return false;
            pos += n;
        }
        if (size-pos < UR_CONTROLS*2) return false;
        for (unsigned i=0; i<UR_CONTROLS; i++,pos+=2)
            if (word(p+pos) > bank->count) return false;
    }
    return pos==size;
}
static void change_screen(uint16_t dest)
{
    screen=dest;
    live_length=0;
}
void ur_disconnect(void)
{
    active=false;
    expected=received=0;
    for (unsigned i=0; i<UR_CONTROLS; i++) announced[i]=false;
}
void ur_set_store(ur_save_fn save) { save_menu=save; }
static void install(struct menu_bank *bank)
{
    ur_disconnect();
    selected_bank ^= 1;
    change_screen(bank->home);
}
bool ur_restore(const uint8_t revision[8], const uint8_t *blob, size_t size)
{
    if (!blob || !revision || size>UR_LIMIT) return false;
    struct menu_bank *bank=&banks[1-selected_bank];
    copy(bank->data,blob,size);
    if (!valid_menu(bank,size)) return false;
    copy(bank->revision,revision,8);
    install(bank);
    return true;
}
void ur_status(uint8_t out[14])
{
    out[0]=1; out[1]=active;
    copy(out+2,banks[selected_bank].revision,8);
    out[10]=(uint8_t)screen; out[11]=(uint8_t)(screen>>8); out[12]=out[13]=0;
}
bool ur_write(const uint8_t *p, size_t n)
{
    if (!n || !p) return false;
    struct menu_bank *stage=&banks[1-selected_bank];
    switch (p[0]) {
    case 1:
        ur_disconnect();
        if (n!=11 || word(p+9)<8 || word(p+9)>UR_LIMIT) return false;
        expected=word(p+9);
        copy(stage->revision,p+1,8);
        return true;
    case 2:
        if (n<4 || !expected || word(p+1)!=received || n-3>(size_t)(expected-received))
            return false;
        copy(stage->data+received,p+3,n-3);
        received+=(uint16_t)(n-3);
        return true;
    case 3:
        if (n!=1 || !expected || received!=expected || !valid_menu(stage,expected))
            return false;
        if (save_menu && !save_menu(stage->revision,stage->data,expected)) return false;
        install(stage);
        return true;
    case 4:
        active = !expected && n==9 && screen && same_revision(banks[selected_bank].revision,p+1);
        return active;
    case 5: {
        if (!active || n<6 || word(p+1)!=screen || p[3] || p[4]) return false;
        unsigned offset=p[5];
        if ((offset && offset!=live_length) || n-6>sizeof(live_text)-offset) return false;
        copy(live_text+offset,p+6,n-6);
        live_length=(uint16_t)(offset+n-6);
        return true;
    }
    default: return false;
    }
}
static const uint8_t *get_view(struct ur_view *v)
{
    struct menu_bank *b=&banks[selected_bank];
    static const uint8_t waiting[]="WAITING FOR HOME ASSISTANT";
    *v=(struct ur_view){0};
    if (!screen) {
        v->title=(struct ur_text){waiting,sizeof(waiting)-1};
        return NULL;
    }
    const uint8_t *p=b->data+b->offsets[screen-1];
    struct ur_text *fields[]={&v->title,&v->body,&v->soft[0],&v->soft[1],&v->soft[2],&v->soft[3]};
    for (size_t i=0;i<6;i++) {
        unsigned n=*p++;
        *fields[i]=(struct ur_text){p,(uint8_t)n};
        p+=n;
    }
    v->live=(struct ur_text){live_text,(uint8_t)live_length};
    return p;
}
void ur_view(struct ur_view *out) { (void)get_view(out); }
bool ur_input(uint16_t control, uint8_t kind, int8_t steps, uint8_t event[8])
{
    if (!screen || !control || control>UR_CONTROLS) return false;
    unsigned key=control-1;
    bool send=active;
    uint16_t source=screen;
    if (kind==UR_TURN) {
        if (control!=20 || !steps) return false;
    } else {
        if (control==20 || steps || kind<UR_PRESS || kind>UR_REPEAT) return false;
        if (kind==UR_PRESS) {
            press_source[key]=source;
            announced[key]=active;
            struct ur_view view;
            const uint8_t *destinations=get_view(&view);
            uint16_t dest=word(destinations+2*key);
            if (dest) change_screen(dest);
        } else {
            send=active && announced[key];
            source=press_source[key];
            if (kind==UR_RELEASE) announced[key]=false;
        }
    }
    if (!send) return false;
    event[0]=(uint8_t)source; event[1]=(uint8_t)(source>>8);
    event[2]=event[3]=0;
    event[4]=(uint8_t)control; event[5]=0;
    event[6]=kind; event[7]=(uint8_t)steps;
    return true;
}
