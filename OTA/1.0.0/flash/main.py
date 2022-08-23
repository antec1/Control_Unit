#!/usr/bin/env python
#
# Copyright (c) 2019, Pycom Limited.
#
# This software is licensed under the GNU GPL version 3 or any
# later version, with permitted additional terms. For more information
# see the Pycom Licence v1.0 document supplied with this file, or
# available at https://www.pycom.io/opensource/licensing
#

print("HI")

import socket
import time
from OTA import WiFiOTA
from time import sleep
import pycom
import binascii

from config import WIFI_SSID, WIFI_PW, SERVER_IP

# Turn on GREEN LED
pycom.heartbeat(False)
pycom.rgbled(0xff00)

ota = WiFiOTA()
ota.connect()

s = socket.socket()
address = socket.getaddrinfo('pybytes.pycom.io',80)
print(address)
s.connect(address[0][-1])
print(address[0][-1][0])
info_for_send = address[0][-1][0]

# make the socket blocking
# (waits for the data to be sent and for the 2 receive windows to expire)
s.setblocking(True)

while True:
    print("I am on")
    #data_update = s.recv(1024).decode()
    data_update = ('Update on V01.10')

    # make the socket non-blocking
    # (because if there's no data received it will block forever...)
    s.setblocking(False)

    print(data_update)

    # Some sort of OTA trigger
    if str(data_update) == ('Update on V01.10'):
        print("Performing OTA")
        # Perform OTA
        ota.update()
        
    sleep(1)

