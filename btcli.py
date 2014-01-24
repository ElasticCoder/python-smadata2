#! /usr/bin/env python

from __future__ import print_function
from __future__ import division
import sys
import os
import signal
import readline
from btsma import *


class Quit(Exception):
    def __init__(self):
        super(Quit, self).__init__("Quit at user request")


def hexdump(data, prefix):
    s = ''
    for i, b in enumerate(data):
        if (i % 16) == 0:
            s += '%s%04x: ' % (prefix, i)
        s += '%02X' % b
        if (i % 16) == 15:
            s += '\n'
        elif (i % 16) == 7:
            s += '-'
        else:
            s += ' '
    if s[-1] == '\n':
        s = s[:-1]
    return s


def dump_outer(prefix, from_, to_, type_, payload):
    print("%s%s -> %s TYPE %02X" % (prefix, from_, to_, type_))
    prefix = prefix + "    "
    if type_ == OTYPE_HELLO:
        print("%sHELLO!" % prefix)
    elif type_ == OTYPE_ERROR:
        print("%sERROR in previous packet:" % prefix)
        print(hexdump(payload[4:], prefix + "    "))


def dump_ppp_raw(prefix, payload):
    info = ""
    if payload[0] == 0x7e:
        info += " frame begins"
    if payload[-1] == 0x7e:
        info += " frame ends"
    print("%sPartial PPP data%s" % (prefix, info))


def dump_ppp(prefix, protocol, payload):
    print("%sPPP frame; protocol 0x%04x [%d bytes]" 
          % (prefix, protocol, len(payload)))
    print(hexdump(payload, prefix + "    "))


def a65602str(addr):
    return "%02X.%02X.%02X.%02X.%02X.%02X" % tuple(addr)

def dump_6560(prefix, from2, to2, x1, x2, x3, x4, x5, x6, counter, payload):
    print("%sSMA %s => %s (pkt %d)" % (prefix, a65602str(from2),
                                       a65602str(to2), counter))
    print("%sCTRL %02x %02x | %02x %02x | %02x %02x" % (prefix, x1, x2, x3,
                                                        x4, x5, x6))
    print(hexdump(payload, prefix + "    "))

class BTSMAConnectionCLI(BTSMAConnection):
    def __init__(self, addr):
        super(BTSMAConnectionCLI, self).__init__(addr)
        print("Connected %s -> %s"
              % (self.local_addr, self.remote_addr))
        self.rxpid = None
        self.counter = 0

    def __del__(self):
        if self.rxpid:
            os.kill(self.rxpid, signal.SIGTERM)

    def rxloop(self):
        while True:
            self.rx()

    def start_rxthread(self):
        self.rxpid = os.fork()
        if self.rxpid == 0:
            while True:
                try:
                    self.rxloop()
                except Exception as e:
                    print(e)

    def rx_raw(self, pkt):
        print("\n" + hexdump(pkt, "Rx< "))
        super(BTSMAConnectionCLI, self).rx_raw(pkt)

    def rx_outer(self, from_, to_, type_, payload):
        dump_outer("Rx<     ", from_, to_, type_, payload)
        if type_ == OTYPE_VARVAL:
            varid = payload[1]
            print("Rx<         VARVAL 0x%02x" % varid)
            if varid == OVAR_SIGNAL:
                print("Rx<             Signal level %0.1f%%"
                      % (payload[5] / 255 * 100))
        elif (type_ in [OTYPE_PPP, OTYPE_PPP2]):
            dump_ppp_raw("Rx<         ", payload)
        super(BTSMAConnectionCLI, self).rx_outer(from_, to_,
                                                 type_, payload)

    def rx_ppp(self, from_, protocol, payload):
        dump_ppp("Rx<         ", protocol, payload)
        super(BTSMAConnectionCLI, self).rx_ppp(from_, protocol, payload)

    def rx_6560(self, from2, to2, x1, x2, x3, x4, x5, x6, counter, payload):
        dump_6560("Rx<             ", from2, to2, x1, x2, x3, x4, x5, x6,
                  counter, payload)

    def tx_raw(self, pkt):
        super(BTSMAConnectionCLI, self).tx_raw(pkt)
        print("\n" + hexdump(pkt, "Tx> "))

    def tx_outer(self, from_, to_, type_, payload):
        super(BTSMAConnectionCLI, self).tx_outer(from_, to_,
                                                 type_, payload)
        dump_outer("Tx>     ", from_, to_, type_, payload)
        if type_ == OTYPE_GETVAR:
            varid = payload[1]
            print("Tx>         GETVAR 0x%02x" % varid)

    def tx_ppp(self, to_, protocol, payload):
        super(BTSMAConnectionCLI, self).tx_ppp(to_, protocol, payload)
        dump_ppp("Tx>         ", protocol, payload)

    def tx_6560(self, from2, to2, x1, x2, x3, x4, x5, x6, counter, payload):
        super(BTSMAConnectionCLI, self).tx_6560(from2, to2, x1, x2, x3, x4, x5, x6,
                                                counter, payload)
        dump_6560("Tx>             ", from2, to2, x1, x2, x3, x4, x5, x6,
                  counter, payload)

    def cli(self):
        while True:
            sys.stdout.write("BTSMA %s >> " % self.remote_addr)
            try:
                line = raw_input().split()
            except EOFError:
                return

            if not line:
                continue

            cmd = 'cmd_' + line[0].lower()
            try:
                getattr(self, cmd)(*line[1:])
            except Quit:
                return
            except Exception as e:
                print("ERROR! %s" % e)

    def cmd_quit(self):
        raise Quit()

    def cmd_raw(self, *args):
        pkt = bytearray([int(x,16) for x in args])
        self.tx_raw(pkt)

    def parse_addr(self, addr):
        if addr.lower() == "zero":
            return "00:00:00:00:00:00"
        elif addr.lower() == "local":
            return self.local_addr
        elif addr.lower() == "remote":
            return self.remote_addr
        elif addr.lower() == "bcast":
            return "ff:ff:ff:ff:ff:ff"
        else:
            return addr

    def cmd_send(self, from_, to_, type_, *args):
        from_ = self.parse_addr(from_)
        to_ = self.parse_addr(to_)
        type_ = int(type_, 16)
        payload = bytearray([int(x, 16) for x in args])
        self.tx_outer(from_, to_, type_, payload)

    def cmd_hello(self):
        self.tx_outer("00:00:00:00:00:00", self.remote_addr, OTYPE_HELLO,
                      bytearray('\x00\x00\x04\x70\x00\x01\x00\x00\x00\x00\x01\x00\x00\x00'))

    def cmd_getvar(self, varid):
        varid = int(varid, 16)
        self.tx_outer("00:00:00:00:00:00", self.remote_addr, OTYPE_GETVAR,
                      bytearray([0x00, varid, 0x00]))

    def cmd_ppp(self, protocol, *args):
        protocol = int(protocol, 0)
        payload = bytearray([int(x, 16) for x in args])
        self.tx_ppp("ff:ff:ff:ff:ff:ff", protocol, payload)

    def cmd_send2(self, x1, x2, x3, x4, x5, x6, *args):
        self.counter += 1
        x1 = int(x1, 16)
        x2 = int(x2, 16)
        x3 = int(x3, 16)
        x4 = int(x4, 16)
        x5 = int(x5, 16)
        x6 = int(x6, 16)
        payload = bytearray([int(x, 16) for x in args])
        self.tx_6560(self.local_addr2, self.BROADCAST2,
                     x1, x2, x3, x4, x5, x6, self.counter, payload)

    def cmd_cmd31(self):
        spl = bytearray('\x09\xA0\xFF\xFF\xFF\xFF\xFF\xFF\x00\x00\x78\x00\x3f\x10\xfb\x39\x00\x00\x00\x00\x00\x00\x01\x80\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
        self.tx_ppp("ff:ff:ff:ff:ff:ff", 0x6560, spl)

    def cmd_cmd31a(self):
        spl = bytearray('\x09\xA0\xFF\xFF\xFF\xFF\xFF\xFF\x00\x00\x78\x00\x3f\x10\xfb\x39\x00\x00\x00\x00\x00\x00\x00\x80\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
        self.tx_ppp("ff:ff:ff:ff:ff:ff", 0x6560, spl)


    def cmd_cmd57(self):
        spl = bytearray('\x09\xA0\xFF\xFF\xFF\xFF\xFF\xFF\x00\x00\x78\x00\x3f\x10\xfb\x39\x00\x00\x00\x00\x00\x00\x00\x80\x00\x02\x80\x51\x00\x48\x21\x00\xFF\x48\x21\x00')
        self.tx_ppp("ff:ff:ff:ff:ff:ff", 0x6560, spl)

    def cmd_cmd60(self):
        spl = bytearray('\x09\xa1\xff\xff\xff\xff\xff\xff\x00\x00\x78\x00\x3f\x10\xfb\x39\x00\x00\x00\x00\x00\x00\x00\x80\x00\x02\x00\x51\x00\x00\x20\x00\xff\xff\x50\x00\x0e')
        self.tx_ppp("ff:ff:ff:ff:ff:ff", 0x6560, spl)

    def cmd_cmd82(self):
        spl = bytearray('\x09\xE0\x4e\x00\xe1\x7e\xf6\x7e\x00\x00\x78\x00\x3f\x10\xfb\x39\x00\x00\x00\x00\x00\x00\x01\x80\x00\x02\x00\x70\x00\x27\x0e\x50\x80\x5a\xc3\x52')
        self.tx_ppp("ff:ff:ff:ff:ff:ff", 0x6560, spl)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: btcli.py <BD addr>", file=sys.stderr)
        sys.exit(1)

    cli = BTSMAConnectionCLI(sys.argv[1])

    cli.start_rxthread()
    cli.cli()
