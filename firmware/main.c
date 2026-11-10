/* Beijing clock: UTC internally, UTC+8 for display. SDA PB10, SCL PB11. */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <libopencm3/stm32/rcc.h>
#include <libopencm3/stm32/gpio.h>
#include <libopencm3/stm32/rtc.h>
#include <libopencm3/cm3/systick.h>
#include <libopencm3/usb/usbd.h>
#include <libopencm3/usb/cdc.h>
#include "calibration.h"

#define REG(a) (*(volatile uint32_t *)(a))
#define BKP(n) REG(0x40006c00+4*(n))
#define SDA GPIO10
#define SCL GPIO11
/* Public diagnostic/mailbox layout, exported by the build for ST-Link tools. */
volatile struct {
    uint32_t magic, version, uptime_ms, utc, ms, source, synced, oled_address;
    uint32_t oled_acks, sync_count, sequence, set_sec, set_ms, checksum, applied;
    uint32_t rtc_div, faults;
} clock_status = {.magic=0x424a5431, .version=1};
static volatile uint32_t ticks;
static uint32_t prescale;
static int16_t phase_offset;
static uint8_t framebuffer[512], oled_addr;
static usbd_device *usbdev;
static bool configured;
static char reply[64];
static uint8_t reply_len;
void sys_tick_handler(void) { ticks++; }
static void delay_ms(uint32_t n) { uint32_t t=ticks; while(ticks-t<n) {} }
static void bitwait(void) {
    uint32_t before=REG(0xe0001004);
    while((uint32_t)(REG(0xe0001004)-before)<72) {} /* 1 us at 72 MHz */
}
static void line(uint16_t pin, bool high) { if(high) gpio_set(GPIOB,pin); else gpio_clear(GPIOB,pin); bitwait(); }
static bool scl_high(void) {
    line(SCL,true);
    for(unsigned i=0;i<10000;i++) if(gpio_get(GPIOB,SCL)) return true;
    clock_status.faults |= 1; return false;
}
static void stop(void) { line(SCL,false); line(SDA,false); scl_high(); line(SDA,true); }
static void start(void) { line(SDA,true); scl_high(); line(SDA,false); line(SCL,false); }
static bool send_byte(uint8_t b) {
    for(int i=7;i>=0;i--) { line(SCL,false); line(SDA,(b>>i)&1); if(!scl_high()) return false; }
    line(SCL,false); line(SDA,true); scl_high();
    bool ack=!gpio_get(GPIOB,SDA); line(SCL,false);
    if(ack) clock_status.oled_acks++;
    return ack;
}
static bool oled_probe(uint8_t addr) { start(); bool ok=send_byte(addr<<1); stop(); return ok; }
static bool oled_write(uint8_t control,const uint8_t *data,unsigned n) {
    start(); bool ok=send_byte(oled_addr<<1) && send_byte(control);
    for(unsigned i=0;i<n && ok;i++) ok=send_byte(data[i]);
    stop(); return ok;
}
static void oled_init(void) {
    line(SDA,true); for(unsigned i=0;i<9;i++) {line(SCL,false);scl_high();} stop();
    oled_addr=oled_probe(0x3c)?0x3c:(oled_probe(0x3d)?0x3d:0);
    clock_status.oled_address=oled_addr;
    if(!oled_addr) return;
    const uint8_t init[]={0xae,0xd5,0x80,0xa8,0x1f,0xd3,0,0x40,0x8d,0x14,
        0x20,0,0xa1,0xc8,0xda,0x02,0x81,0x7f,0xd9,0xf1,0xdb,0x40,0xa4,0xa6,0xaf};
    oled_write(0,init,sizeof(init));
}
static const uint8_t digits[10][5]={
 {0x3e,0x51,0x49,0x45,0x3e},{0,0x42,0x7f,0x40,0},{0x42,0x61,0x51,0x49,0x46},
 {0x21,0x41,0x45,0x4b,0x31},{0x18,0x14,0x12,0x7f,0x10},{0x27,0x45,0x45,0x45,0x39},
 {0x3c,0x4a,0x49,0x49,0x30},{1,0x71,9,5,3},{0x36,0x49,0x49,0x49,0x36},
 {6,0x49,0x49,0x29,0x1e}};
static const uint8_t letters[26][5]={
 {0x7e,0x11,0x11,0x11,0x7e},{0x7f,0x49,0x49,0x49,0x36},{0x3e,0x41,0x41,0x41,0x22},
 {0x7f,0x41,0x41,0x22,0x1c},{0x7f,0x49,0x49,0x49,0x41},{0x7f,9,9,9,1},
 {0x3e,0x41,0x49,0x49,0x7a},{0x7f,8,8,8,0x7f},{0,0x41,0x7f,0x41,0},
 {0x20,0x40,0x41,0x3f,1},{0x7f,8,0x14,0x22,0x41},{0x7f,0x40,0x40,0x40,0x40},
 {0x7f,2,0xc,2,0x7f},{0x7f,4,8,0x10,0x7f},{0x3e,0x41,0x41,0x41,0x3e},
 {0x7f,9,9,9,6},{0x3e,0x41,0x51,0x21,0x5e},{0x7f,9,0x19,0x29,0x46},
 {0x46,0x49,0x49,0x49,0x31},{1,1,0x7f,1,1},{0x3f,0x40,0x40,0x40,0x3f},
 {0x1f,0x20,0x40,0x20,0x1f},{0x3f,0x40,0x38,0x40,0x3f},{0x63,0x14,8,0x14,0x63},
 {7,8,0x70,8,7},{0x61,0x51,0x49,0x45,0x43}};
static void pixel(unsigned x,unsigned y) { if(x<128 && y<32) framebuffer[x+128*(y/8)]|=1<<(y%8); }
static void text(unsigned x,unsigned y,const char *s,unsigned scale) {
    while(*s) { char ch=*s++; const uint8_t *g=0; uint8_t p[5]={0};
        if(ch>='0'&&ch<='9')g=digits[ch-'0'];
        else if(ch>='A'&&ch<='Z')g=letters[ch-'A'];
        else { if(ch==':')p[2]=0x24; if(ch=='-')p[0]=p[1]=p[2]=p[3]=p[4]=8; if(ch=='+'){p[2]=0x1c;p[1]=p[3]=8;} g=p; }
        for(unsigned i=0;i<5;i++) for(unsigned j=0;j<7;j++) if(g[i]&(1<<j))
            for(unsigned a=0;a<scale;a++)for(unsigned b=0;b<scale;b++)pixel(x+i*scale+a,y+j*scale+b);
        x+=6*scale;
    }
}
static bool leap(unsigned y) {return y%4==0 && (y%100!=0 || y%400==0);}
static void display(uint32_t utc) {
    memset(framebuffer,0,sizeof(framebuffer)); char s[32];
    if(!clock_status.synced) {text(4,2,"BEIJING UTC+8",1);text(4,14,"WAIT PC TIME",1);}
    else {
        uint32_t local=utc+28800, day=local/86400, sod=local%86400;
        unsigned year=1970,month=1; const uint8_t md[]={31,28,31,30,31,30,31,31,30,31,30,31};
        while(day>=365u+leap(year)){day-=365+leap(year);year++;}
        while(day>=md[month-1]+(unsigned)(month==2&&leap(year))){day-=md[month-1]+(month==2&&leap(year));month++;}
        snprintf(s,sizeof(s),"%04u-%02u-%02u  BJT",year,month,(unsigned)day+1);text(1,0,s,1);
        snprintf(s,sizeof(s),"%02lu:%02lu:%02lu",(unsigned long)sod/3600,(unsigned long)(sod/60)%60,(unsigned long)sod%60);text(16,11,s,2);
        /* Bottom row: sync marker + source, kept away from the large digits. */
        text(1,25,clock_status.source==1?"L":"H",1);
    }
    if(oled_addr) for(unsigned page=0;page<4;page++) {
        uint8_t cmd[]={0x21,0,127,0x22,page,page};oled_write(0,cmd,sizeof(cmd));
        for(unsigned col=0;col<128;col+=16) {oled_write(0x40,framebuffer+page*128+col,16);if(usbdev)usbd_poll(usbdev);}
    }
}
static uint64_t raw_ms(void) {
    uint32_t a,b,d;
    do {a=rtc_get_counter_val();d=rtc_get_prescale_div_val();b=rtc_get_counter_val();}while(a!=b);
    clock_status.rtc_div=d;
    return (uint64_t)a*1000+(uint64_t)(prescale-d)*1000/(prescale+1);
}
static void snapshot(void) {
    uint64_t now=raw_ms()+phase_offset;
    clock_status.utc=now/1000;clock_status.ms=now%1000;clock_status.uptime_ms=ticks;
}
static bool set_time(uint32_t seconds,uint32_t ms) {
    if(seconds<1704067200u || seconds>4102444799u || ms>=1000) return false;
    BKP(1)=0; /* Invalidate before changing the counter/phase pair. */
    rtc_set_counter_val(seconds);
    phase_offset=(int32_t)ms-(int32_t)(raw_ms()%1000);
    BKP(2)=(uint16_t)phase_offset; BKP(3)=clock_status.source; BKP(1)=0xb171;
    clock_status.synced=1;clock_status.sync_count++;snapshot();return true;
}
static void rtc_init(void) {
    REG(0x4002101c)|=(1<<28)|(1<<27);REG(0x40007000)|=1<<8;
    uint32_t saved=REG(0x40021020);
    bool valid_source=BKP(3)==1 || (BKP(3)==3 && !(REG(0x40021024)&(1u<<27)));
    if((saved&(1<<15)) && BKP(1)==0xb171 && ((saved>>8)&3)==BKP(3) && valid_source) {
        clock_status.source=BKP(3);prescale=clock_status.source==1?32767:62499;
        phase_offset=(int16_t)BKP(2);clock_status.synced=1;
    } else {
        REG(0x40021020)|=1<<16;REG(0x40021020)&=~(1<<16);
        REG(0x40021020)|=1;uint32_t t=ticks;
        while(!(REG(0x40021020)&2) && ticks-t<5000) {}
        bool lse=(REG(0x40021020)&2)!=0;
        clock_status.source=lse?1:3;prescale=lse?32767:62499;
        REG(0x40021020)|=(clock_status.source<<8)|(1<<15);
    }
    RTC_CRL&=~RTC_CRL_RSF;while(!(RTC_CRL&RTC_CRL_RSF)){}
    if(!clock_status.synced){rtc_set_prescale_val(prescale);rtc_set_counter_val(0);}
    bool this_board=REG(0x1ffff7e8)==CLOCK_CAL_UID0 && REG(0x1ffff7ec)==CLOCK_CAL_UID1 && REG(0x1ffff7f0)==CLOCK_CAL_UID2;
    REG(0x40006c2c)=(clock_status.source==1 && this_board)?CLOCK_LSE_CALIBRATION:0;
    REG(0x40021024)|=1u<<24; /* Clear reset flags after examining POR for HSE. */
}
/* USB CDC: binary 16-byte set packet: BJT1, UTC uint32, ms uint32, XOR checksum.
 * INFO\n returns BJT1 UTC ms source sync_count, to identify this device. */
static const struct usb_device_descriptor dev={.bLength=USB_DT_DEVICE_SIZE,.bDescriptorType=USB_DT_DEVICE,.bcdUSB=0x0200,.bDeviceClass=USB_CLASS_CDC,.bMaxPacketSize0=64,.idVendor=0x1209,.idProduct=0xb103,.bcdDevice=0x0100,.iManufacturer=1,.iProduct=2,.iSerialNumber=3,.bNumConfigurations=1};
static const struct usb_endpoint_descriptor comm_ep[]={{.bLength=USB_DT_ENDPOINT_SIZE,.bDescriptorType=USB_DT_ENDPOINT,.bEndpointAddress=0x83,.bmAttributes=USB_ENDPOINT_ATTR_INTERRUPT,.wMaxPacketSize=16,.bInterval=255}};
static const struct usb_endpoint_descriptor data_ep[]={
 {.bLength=USB_DT_ENDPOINT_SIZE,.bDescriptorType=USB_DT_ENDPOINT,.bEndpointAddress=0x01,.bmAttributes=USB_ENDPOINT_ATTR_BULK,.wMaxPacketSize=64,.bInterval=1},
 {.bLength=USB_DT_ENDPOINT_SIZE,.bDescriptorType=USB_DT_ENDPOINT,.bEndpointAddress=0x82,.bmAttributes=USB_ENDPOINT_ATTR_BULK,.wMaxPacketSize=64,.bInterval=1}};
static const struct __attribute__((packed)) {
 struct usb_cdc_header_descriptor h;struct usb_cdc_call_management_descriptor m;
 struct usb_cdc_acm_descriptor a;struct usb_cdc_union_descriptor u;
} functional={{5,CS_INTERFACE,USB_CDC_TYPE_HEADER,0x0110},{5,CS_INTERFACE,USB_CDC_TYPE_CALL_MANAGEMENT,0,1},{4,CS_INTERFACE,USB_CDC_TYPE_ACM,2},{5,CS_INTERFACE,USB_CDC_TYPE_UNION,0,1}};
static const struct usb_interface_descriptor comm[]={{.bLength=USB_DT_INTERFACE_SIZE,.bDescriptorType=USB_DT_INTERFACE,.bInterfaceNumber=0,.bNumEndpoints=1,.bInterfaceClass=USB_CLASS_CDC,.bInterfaceSubClass=USB_CDC_SUBCLASS_ACM,.bInterfaceProtocol=USB_CDC_PROTOCOL_AT,.endpoint=comm_ep,.extra=&functional,.extralen=sizeof(functional)}};
static const struct usb_interface_descriptor data[]={{.bLength=USB_DT_INTERFACE_SIZE,.bDescriptorType=USB_DT_INTERFACE,.bInterfaceNumber=1,.bNumEndpoints=2,.bInterfaceClass=USB_CLASS_DATA,.endpoint=data_ep}};
static const struct usb_interface ifaces[]={{.num_altsetting=1,.altsetting=comm},{.num_altsetting=1,.altsetting=data}};
static const struct usb_config_descriptor config={.bLength=USB_DT_CONFIGURATION_SIZE,.bDescriptorType=USB_DT_CONFIGURATION,.bNumInterfaces=2,.bConfigurationValue=1,.bmAttributes=0x80,.bMaxPower=50,.interface=ifaces};
static char serial_number[25];
static const char *strings[]={"Beijing Clock","STM32 Beijing Clock",serial_number};
static uint8_t control_buffer[128],rx[64];static unsigned rxlen;
static void make_reply(void) {snapshot();reply_len=snprintf(reply,sizeof(reply),"BJT1 %lu %lu %lu %lu\n",(unsigned long)clock_status.utc,(unsigned long)clock_status.ms,(unsigned long)clock_status.source,(unsigned long)clock_status.sync_count);}
static void received(usbd_device *d,uint8_t ep) {
    uint8_t buf[64];int n=usbd_ep_read_packet(d,ep,buf,sizeof(buf));
    for(int i=0;i<n;i++) {
        if(rxlen>=sizeof(rx))rxlen=0;
        rx[rxlen++]=buf[i];
        if(rxlen==5 && !memcmp(rx,"INFO\n",5)){make_reply();rxlen=0;}
        else if(rxlen==16 && !memcmp(rx,"BJT1",4)) {
            uint32_t s,m,c;memcpy(&s,rx+4,4);memcpy(&m,rx+8,4);memcpy(&c,rx+12,4);
            if(c==(s^m^0x314a5442u) && set_time(s,m))make_reply();rxlen=0;
        } else if(rxlen>=5 && memcmp(rx,"BJT1",4) && memcmp(rx,"INFO\n",5))rxlen=0;
    }
}
static enum usbd_request_return_codes control(usbd_device *d,struct usb_setup_data *req,uint8_t **buf,uint16_t *len,usbd_control_complete_callback *complete) {
    (void)d;(void)complete;
    if(req->wIndex!=0) return USBD_REQ_NOTSUPP;
    if(req->bRequest==USB_CDC_REQ_SET_CONTROL_LINE_STATE)return USBD_REQ_HANDLED;
    if(req->bRequest==USB_CDC_REQ_SET_LINE_CODING)return *len==7?USBD_REQ_HANDLED:USBD_REQ_NOTSUPP;
    if(req->bRequest==USB_CDC_REQ_GET_LINE_CODING){const uint8_t coding[]={0,0xc2,1,0,0,0,8};memcpy(*buf,coding,7);*len=7;return USBD_REQ_HANDLED;}
    return USBD_REQ_NOTSUPP;
}
static void set_config(usbd_device *d,uint16_t value) {
    configured=value!=0;rxlen=reply_len=0;if(!value)return;
    usbd_ep_setup(d,0x01,USB_ENDPOINT_ATTR_BULK,64,received);usbd_ep_setup(d,0x82,USB_ENDPOINT_ATTR_BULK,64,0);usbd_ep_setup(d,0x83,USB_ENDPOINT_ATTR_INTERRUPT,16,0);
    usbd_register_control_callback(d,USB_REQ_TYPE_CLASS|USB_REQ_TYPE_INTERFACE,USB_REQ_TYPE_TYPE|USB_REQ_TYPE_RECIPIENT,control);
}
int main(void) {
    rcc_clock_setup_pll(&rcc_hse_configs[RCC_CLOCK_HSE8_72MHZ]);
    REG(0xe000edfc)|=1u<<24;REG(0xe0001000)|=1; /* DWT cycle counter */
    systick_set_clocksource(STK_CSR_CLKSOURCE_AHB);systick_set_reload(71999);systick_interrupt_enable();systick_counter_enable();
    rcc_periph_clock_enable(RCC_GPIOA);rcc_periph_clock_enable(RCC_GPIOB);rcc_periph_clock_enable(RCC_GPIOC);rcc_periph_clock_enable(RCC_USB);
    gpio_set_mode(GPIOC,GPIO_MODE_OUTPUT_2_MHZ,GPIO_CNF_OUTPUT_PUSHPULL,GPIO13);gpio_set(GPIOC,GPIO13);
    gpio_set(GPIOB,SDA|SCL);gpio_set_mode(GPIOB,GPIO_MODE_OUTPUT_2_MHZ,GPIO_CNF_OUTPUT_OPENDRAIN,SDA|SCL);
    delay_ms(100);oled_init();display(0);rtc_init();
    /* Force USB re-enumeration even on boards with a fixed D+ pull-up. */
    gpio_set_mode(GPIOA,GPIO_MODE_OUTPUT_2_MHZ,GPIO_CNF_OUTPUT_PUSHPULL,GPIO12);gpio_clear(GPIOA,GPIO12);delay_ms(30);
    gpio_set_mode(GPIOA,GPIO_MODE_INPUT,GPIO_CNF_INPUT_FLOAT,GPIO11|GPIO12);
    snprintf(serial_number,sizeof(serial_number),"%08lX%08lX%08lX",(unsigned long)REG(0x1ffff7e8),(unsigned long)REG(0x1ffff7ec),(unsigned long)REG(0x1ffff7f0));
    usbdev=usbd_init(&st_usbfs_v1_usb_driver,&dev,&config,strings,3,control_buffer,sizeof(control_buffer));usbd_register_set_config_callback(usbdev,set_config);
    uint32_t last_draw=0,last_probe=ticks;
    while(1) {
        usbd_poll(usbdev);
        if(configured && reply_len && usbd_ep_write_packet(usbdev,0x82,reply,reply_len))reply_len=0;
        if(clock_status.sequence!=clock_status.applied) {
            uint32_t q=clock_status.sequence,s=clock_status.set_sec,m=clock_status.set_ms;
            if(clock_status.checksum==(s^m^q^0x314a5442u) && set_time(s,m))clock_status.applied=q;
        }
        snapshot();
        if(ticks-last_draw>=100) {last_draw=ticks;display(clock_status.utc);if(clock_status.utc&1)gpio_set(GPIOC,GPIO13);else gpio_clear(GPIOC,GPIO13);}
        if(!oled_addr && ticks-last_probe>2000){last_probe=ticks;oled_init();}
    }
}
