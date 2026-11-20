#include "keys.h"
static const uint8_t bits[19]={0,1,2,3,4,6,8,7,5,13,9,10,11,14,17,12,16,15,18};
static uint32_t prior;
static uint16_t ticks[19];
static bool baseline;
static uint8_t last_wheel;
static int wheel_motion;
void keys_reset(void)
{
    baseline=false;
    last_wheel=0;
    wheel_motion=0;
    for (unsigned i=0;i<19;i++) ticks[i]=0;
}
void keys_sample(uint32_t mask,uint8_t wheel,ur_key_fn emit)
{
    if (!baseline) {
        prior=mask;
        last_wheel=wheel;
        baseline=true;
        return;
    }
    for (unsigned i=0;i<19;i++) {
        uint32_t bit=1u<<bits[i];
        if ((prior^mask)&bit) {
            ticks[i]=(mask&bit) ? 1 : 0;
            emit(i+1,(mask&bit) ? UR_PRESS : UR_RELEASE,0);
        } else if ((mask&bit) && ticks[i]) {
            if (++ticks[i]==26) emit(i+1,UR_HOLD,0);
            else if (ticks[i]>=33) {
                emit(i+1,UR_REPEAT,0);
                ticks[i]=26;
            }
        }
    }
    prior=mask;
    /* Relative motion between nearby samples. Zero is touch-up. Ignore large
       jumps at wrap/recontact until the electrode range is calibrated on V06. */
    if (wheel && last_wheel) {
        int delta=(int)wheel-last_wheel;
        if (delta>=-16 && delta<=16) {
            wheel_motion+=delta;
            int steps=wheel_motion/4;
            if (steps) {
                emit(20,UR_TURN,(int8_t)steps);
                wheel_motion-=steps*4;
            }
        } else wheel_motion=0;
    } else wheel_motion=0;
    last_wheel=wheel;
}
