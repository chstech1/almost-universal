/* Executes the application on Cortex-M3. Only board pins and radio SDK calls are simulated. */
#include "board.h"
#include "gap_api.h"
#include "gatt_api.h"
#include "os_timer.h"
void test_fail(const char *s);
void test_print(const char *s);
void user_entry_after_stack_init(void);
#define CHECK(x) do { if (!(x)) test_fail(#x); } while (0)

static gap_callback_func_t gap;
static gatt_service_t *service;
static os_timer_func_t tick;
static uint32_t mask;
static unsigned begins, presses, holds, repeats, releases, advertised;
static unsigned control,event_attr,status,ccc;
static const uint8_t svc_uuid[]={1,16,208,168,57,157,40,154,105,76,97,126,1,0,247,19};
void board_start(void) { begins++; }
void board_redraw(void) {}
void board_draw_slice(void) {}
bool board_sample(uint32_t *m,uint8_t *w) { *m=mask; *w=0; return true; }
void gap_set_cb_func(gap_callback_func_t cb) { gap=cb; }
void gap_set_advertising_param(gap_adv_param_t *p) { CHECK(p->adv_mode==GAP_ADV_MODE_UNDIRECT); }
void gap_set_advertising_data(uint8_t *p,uint16_t n)
{
    CHECK(n==21 && p[3]==17 && p[4]==7);
    for (unsigned i=0;i<16;i++) CHECK(p[5+i]==svc_uuid[i]);
}
void gap_set_advertising_rsp_data(uint8_t *p,uint16_t n) { CHECK(n==10 && p[0]==9); }
void gap_start_advertising(uint16_t on) { (void)on; advertised++; }
void gap_disconnect_req(uint8_t idx) { (void)idx; }
uint8_t gatt_add_service(gatt_service_t *s)
{
    service=s;
    for (unsigned i=0;i<s->att_nb;i++) {
        const gatt_attribute_t *a=&s->p_att_tb[i];
        if (a->uuid.size==16) {
            switch (a->uuid.p_uuid[12]) {
            case 2: control=i; CHECK(a->prop&GATT_PROP_WRITE_REQ); break;
            case 3: event_attr=i; CHECK(a->prop&GATT_PROP_NOTI); break;
            case 4: status=i; CHECK(a->prop&GATT_PROP_READ); break;
            }
        } else if (a->uuid.p_uuid[0]==2 && a->uuid.p_uuid[1]==0x29) ccc=i;
    }
    return 9;
}
void os_timer_init(os_timer_t *t,os_timer_func_t cb,void *arg) { (void)t; (void)arg; tick=cb; }
void os_timer_start(os_timer_t *t,uint32_t ms,bool repeat) { (void)t; CHECK(ms==20 && repeat); }
void gatt_notification(gatt_ntf_t n)
{
    CHECK(n.conidx==3 && n.svc_id==9 && n.att_idx==event_attr && n.data_len==8);
    uint8_t *p=n.p_data;
    CHECK(p[0]==1 && !p[1] && !p[2] && !p[3] && p[4]==1 && !p[5] && !p[7]);
    switch(p[6]) {
    case UR_PRESS: presses++; break; case UR_RELEASE: releases++; break;
    case UR_HOLD: holds++; break; case UR_REPEAT: repeats++; break;
    default: test_fail("Unexpected event kind");
    }
}
static unsigned request(unsigned attr,gatt_msg_evt_t kind,uint8_t *p,unsigned n)
{
    gatt_msg_t m={.conn_idx=3,.att_idx=attr,.msg_evt=kind,
                  .param.msg={.msg_len=(uint16_t)n,.p_msg_data=p}};
    return service->gatt_msg_handler(&m);
}
int main(void)
{
    user_entry_after_stack_init();
    CHECK(begins==1 && gap && tick && service && control && event_attr && status && ccc);
    gap_event_t ev={.type=GAP_EVT_ALL_SVC_ADDED};
    gap(&ev); CHECK(advertised==1);
    ev.type=GAP_EVT_SLAVE_CONNECT; ev.param.slave_connect.conidx=3; gap(&ev);
    uint8_t subscribe[]={1,0}, readback[14], enable[]={4,1,2,3,4,5,6,7,8};
    CHECK(request(ccc,GATTC_MSG_WRITE_REQ,subscribe,2)==2);
    uint8_t package[8+1+6+1+1+6+3+40]={'U','R','M','1',1,0,1,0,6,'O','f','f','i','c','e',0,6,'L','i','g','h','t','s'};
    uint8_t begin[]={1,1,2,3,4,5,6,7,8,sizeof(package),0}, commit=3;
    CHECK(request(control,GATTC_MSG_WRITE_REQ,begin,sizeof(begin))==sizeof(begin));
    for(unsigned off=0;off<sizeof(package);) {
        uint8_t p[20]={2,(uint8_t)off,0};
        unsigned n=sizeof(package)-off;
        if(n>17) n=17;
        for(unsigned i=0;i<n;i++) p[3+i]=package[off+i];
        CHECK(request(control,GATTC_MSG_WRITE_REQ,p,n+3)==n+3); off+=n;
    }
    CHECK(request(control,GATTC_MSG_WRITE_REQ,&commit,1)==1);
    CHECK(request(control,GATTC_MSG_WRITE_REQ,enable,9)==9);
    CHECK(request(status,GATTC_MSG_READ_REQ,readback,14)==14 && readback[1] && readback[10]==1);
    tick(NULL); tick(NULL);
    mask=1;
    for(unsigned n=0;n<40;n++) tick(NULL);
    CHECK(presses==1 && holds==1 && repeats>0);
    mask=0; tick(NULL); tick(NULL);
    mask=1; tick(NULL); tick(NULL);
    mask=0; tick(NULL); tick(NULL);
    CHECK(presses==2 && releases==2);
    ev.type=GAP_EVT_DISCONNECT; ev.param.disconnect.conidx=3; gap(&ev);
    mask=1; tick(NULL); tick(NULL); CHECK(presses==2);
    test_print("PASS: discovery UUID, real GATT service, menu sync, two soft A presses, no offline replay");
    return 0;
}
