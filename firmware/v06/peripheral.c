#include "remote.h"
#include "keys.h"
#include "board.h"
#include "gap_api.h"
#include "gatt_api.h"
#include "os_timer.h"

/* BLE transmits 128-bit UUID fields in little-endian order. */
#define UR_UUID(n) {0x01,0x10,0xd0,0xa8,0x39,0x9d,0x28,0x9a,0x69,0x4c,0x61,0x7e,(n),0x00,0xf7,0x13}
#define DECL(type) {{2,{(type),0x28}},GATT_PROP_READ,0,NULL}
enum { SERVICE, CONTROL_DECL, CONTROL, EVENT_DECL, EVENT, CCC, STATUS_DECL, STATUS, COUNT };
static uint8_t service_uuid[]=UR_UUID(1);
static const gatt_attribute_t attributes[COUNT]={
    [SERVICE]={{2,{0x00,0x28}},GATT_PROP_READ,16,service_uuid},
    [CONTROL_DECL]=DECL(3),
    [CONTROL]={{16,UR_UUID(2)},GATT_PROP_WRITE|GATT_PROP_WRITE_REQ,244,NULL},
    [EVENT_DECL]=DECL(3),
    [EVENT]={{16,UR_UUID(3)},GATT_PROP_NOTI,8,NULL},
    [CCC]={{2,{2,0x29}},GATT_PROP_READ|GATT_PROP_WRITE|GATT_PROP_WRITE_REQ,2,NULL},
    [STATUS_DECL]=DECL(3),
    [STATUS]={{16,UR_UUID(4)},GATT_PROP_READ,14,NULL},
};
static uint8_t service_id, connection=0xff;
static bool subscribed, dirty;
static bool have_sample;
static uint32_t last_sample;
static os_timer_t poll_timer;
static uint16_t handle_gatt(gatt_msg_t *msg)
{
    if (msg->conn_idx!=connection) return 0;
    uint8_t *data=msg->param.msg.p_msg_data;
    uint16_t len=msg->param.msg.msg_len;
    if (msg->msg_evt==GATTC_MSG_READ_REQ) {
        if (msg->att_idx==STATUS) { ur_status(data); return 14; }
        if (msg->att_idx==CCC) { data[0]=subscribed; data[1]=0; return 2; }
    }
    if (msg->msg_evt==GATTC_MSG_WRITE_REQ) {
        if (msg->att_idx==CCC && len==2 && data[0]<=1 && !data[1]) {
            subscribed=data[0];
            if (!subscribed) ur_disconnect();
            return len;
        }
        if (msg->att_idx==CONTROL && ur_write(data,len)) {
            if (data[0]==3 || data[0]==5) dirty=true;
            return len;
        }
    }
    return 0;
}
static gatt_service_t service={attributes,COUNT,handle_gatt};

static void advertise(void)
{
    static uint8_t advertisement[]={2,1,6,17,7,
        0x01,0x10,0xd0,0xa8,0x39,0x9d,0x28,0x9a,0x69,0x4c,0x61,0x7e,1,0,0xf7,0x13};
    static uint8_t response[]={9,9,'U','R',' ','M','e','n','u','s'};
    gap_adv_param_t p={.adv_mode=GAP_ADV_MODE_UNDIRECT,.adv_addr_type=GAP_ADDR_TYPE_PUBLIC,
        .adv_chnl_map=GAP_ADV_CHAN_ALL,.adv_filt_policy=GAP_ADV_ALLOW_SCAN_ANY_CON_ANY,
        .adv_intv_min=160,.adv_intv_max=160};
    gap_set_advertising_param(&p);
    gap_set_advertising_data(advertisement,sizeof(advertisement));
    gap_set_advertising_rsp_data(response,sizeof(response));
    gap_start_advertising(0);
}
static void gap_event(gap_event_t *event)
{
    switch (event->type) {
    case GAP_EVT_ALL_SVC_ADDED: advertise(); break;
    case GAP_EVT_SLAVE_CONNECT:
        if (connection!=0xff) { gap_disconnect_req(event->param.slave_connect.conidx); break; }
        connection=event->param.slave_connect.conidx;
        subscribed=false;
        ur_disconnect();
        break;
    case GAP_EVT_DISCONNECT:
        if (connection!=event->param.disconnect.conidx) break;
        connection=0xff;
        subscribed=false;
        ur_disconnect();
        advertise();
        break;
    default: break;
    }
}
static void input(uint16_t key,uint8_t phase,int8_t steps)
{
    uint8_t before[14], after[14], packet[8];
    ur_status(before);
    bool send=ur_input(key,phase,steps,packet);
    ur_status(after);
    if (before[10]!=after[10]) dirty=true;
    if (send && subscribed && connection!=0xff) {
        gatt_ntf_t notification={.conidx=connection,.svc_id=service_id,.att_idx=EVENT,
                                  .p_data=packet,.data_len=sizeof(packet)};
        gatt_notification(notification);
    }
}
static void poll(void *arg)
{
    (void)arg;
    uint32_t mask;
    uint8_t wheel;
    if (board_sample(&mask,&wheel)) {
        if (have_sample && mask==last_sample) keys_sample(mask,wheel,input);
        last_sample=mask;
        have_sample=true;
    } else have_sample=false;
    if (dirty) { dirty=false; board_redraw(); }
    board_draw_slice();
}
/* SDK calls this once from the application task after bringing the radio up. */
void user_entry_after_stack_init(void)
{
    keys_reset();
    board_start();
    gap_set_cb_func(gap_event);
    service_id=gatt_add_service(&service);
    os_timer_init(&poll_timer,poll,NULL);
    os_timer_start(&poll_timer,20,true);
}
