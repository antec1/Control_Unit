#!/usr/bin/env python
#
# Copyright (c) 2019, Pycom Limited.
#
# This software is licensed under the GNU GPL version 3 or any
# later version, with permitted additional terms. For more information
# see the Pycom Licence v1.0 document supplied with this file, or
# available at https://www.pycom.io/opensource/licensing
#

import urequests
import network
from network import LTE
import socket
import machine
import ujson
import uhashlib
import ubinascii
import gc
import pycom
import os
import time
import urequests as requests


last_client_socket = None
server_socket = None

# Try to get version number
try:
    from OTA_VERSION import VERSION
except ImportError:
    VERSION = '1.0.0'

class OTA():
    # The following two methods need to be implemented in a subclass for the
    # specific transport mechanism e.g. WiFi

    def connect(self):
        raise NotImplementedError()

    def get_data(self, req, dest_path=None, hash=False):
        raise NotImplementedError()

    # OTA methods

    def get_current_version(self):
        return VERSION

    def get_update_manifest(self):
        print(self.get_current_version())
        req = "manifest.json?current_ver={}".format(self.get_current_version())
        time.sleep(3)
        manifest_data = self.get_data(req).decode()
        print(manifest_data + "MMMM")
        manifest = ujson.load(manifest_data)
        gc.collect()
        return manifest

    def update(self):
        manifest = self.get_update_manifest()
        if manifest is None:
            print("Already on the latest version")
            return

        # Download new files and verify hashes
        for f in manifest['new'] + manifest['update']:
            # Upto 5 retries
            for _ in range(5):
                try:
                    self.get_file(f)
                    break
                except Exception as e:
                    print("HA")
                    print(e)
                    msg = "Error downloading `{}` retrying..."
                    print(msg.format(f['URL']))
            else:
                raise Exception("Failed to download `{}`".format(f['URL']))

        # Backup old files
        # only once all files have been successfully downloaded
        for f in manifest['update']:
            self.backup_file(f)

        # Rename new files to proper name
        for f in manifest['new'] + manifest['update']:
            new_path = "{}.new".format(f['dst_path'])
            dest_path = "{}".format(f['dst_path'])

            os.rename(new_path, dest_path)

        # `Delete` files no longer required
        # This actually makes a backup of the files incase we need to roll back
        for f in manifest['delete']:
            self.delete_file(f)

        # Flash firmware
        if "firmware" in manifest:
            self.write_firmware(manifest['firmware'])

        # Save version number
        try:
            self.backup_file({"dst_path": "/flash/OTA_VERSION.py"})
        except OSError:
            pass  # There isnt a previous file to backup
        with open("/flash/OTA_VERSION.py", 'w') as fp:
            fp.write("VERSION = '{}'".format(manifest['version']))
        from OTA_VERSION import VERSION

        return "OTA Done"

        # Reboot the device to run the new decode
        machine.reset()

    def get_file(self, f):
        new_path = "{}.new".format(f['dst_path'])

        # If a .new file exists from a previously failed update delete it
        try:
            os.remove(new_path)
        except OSError:
            pass  # The file didnt exist

        # Download new file with a .new extension to not overwrite the existing
        # file until the hash is verified.
        hash = self.get_data(f['URL'].split("/", 3)[-1],
                             dest_path=new_path,
                             hash=True)

        # Hash mismatch
        if hash != f['hash']:
            print(hash, f['hash'])
            msg = "Downloaded file's hash does not match expected hash"
            raise Exception(msg)

    def backup_file(self, f):
        bak_path = "{}.bak".format(f['dst_path'])
        dest_path = "{}".format(f['dst_path'])

        # Delete previous backup if it exists
        try:
            os.remove(bak_path)
        except OSError:
            pass  # There isnt a previous backup

        # Backup current file
        os.rename(dest_path, bak_path)

    def delete_file(self, f):
        bak_path = "/{}.bak_del".format(f)
        dest_path = "/{}".format(f)

        # Delete previous delete backup if it exists
        try:
            os.remove(bak_path)
        except OSError:
            pass  # There isnt a previous delete backup

        # Backup current file
        os.rename(dest_path, bak_path)

    def write_firmware(self, f):
        hash = self.get_data(f['URL'].split("/", 3)[-1],
                             hash=True,
                             firmware=True)
        # TODO: Add verification when released in future firmware


class WiFiOTA(OTA):
    def __init__(self):
        pass
    def connect(self):
        lte = LTE()
        lte.reset()
        info = lte.iccid()
        print(info)
        #some carriers have special requirements, check print(lte.send_at_cmd("AT+SQNCTM=?")) to see if your carrier is listed.
        #when using verizon, use
        #lte.init(carrier=verizon)
        #when usint AT&T use,
        #lte.init(carrier=at&t)

        #some carriers do not require an APN
        #also, check the band settings with your carrier
        lte.attach(band=20, apn="freeeway")
        print("attaching..",end='')
        while not lte.isattached():
            try:
                time.sleep(1)
                print('.',end='')
                lte_info = lte.send_at_cmd('AT!="fsm"')
                print(lte_info)         # get the System FSM
                lte_info_att = lte.send_at_cmd('AT+cind?').split(": ")
                print(lte_info_att)
            except:
                print("Busy in data state!")
        print("attached!")

        lte.connect()
        print("connecting [##",end='')
        fail_lte = 0
        while not lte.isconnected():
            try:
                time.sleep(0.5)
                print('#',end='')
                print(lte.send_at_cmd('AT!="fsm"'))
                fail_lte +=1
                if fail_lte > 100:
                    print("Connection is failed. Please reboot system or call support")
            except:
                pass
        print("] connected!")

    def _http_get(self, path, host):
        req_fmt = 'GET /{} HTTP/1.1\r\nHost: {}\r\n\r\n'
        req = req_fmt.format(path, host)
        print(req)
        return req

    def get_data(self, req, dest_path=None, hash=False, firmware=False):
        h = None

        # Connect to server
        print("Requesting: {}".format(req))
        s = socket.socket(socket.AF_INET,
                          socket.SOCK_STREAM,
                          socket.IPPROTO_TCP)
        address = socket.getaddrinfo('pybytes.pycom.io',80)
        print(address)
        s.connect(address[0][-1])

        # Request File
        #s.sendall(self._http_get(req, "{}:{}".format(address[0][-1][0],address[0][-1][1])))
        #s.sendall(self._http_get(req, "{}:{}".format("127.0.0.1",8000)))
        test = self._http_get(req, "{}:{}".format("127.0.0.1",8000))
        print(test)
        print(test.encode())
        s.sendall(test.encode())

        try:
            content = bytearray()
            fp = None
            if dest_path is not None:
                if firmware:
                    raise Exception("Cannot write firmware to a file")
                fp = open(dest_path, 'wb')

            if firmware:
                pycom.ota_start()

            h = uhashlib.sha1()

            # Get data from server
            result = s.recv(1024)
            print(result)
            s.close()

            start_writing = False
            while (len(result) > 0):
                # Ignore the HTTP headers
                if not start_writing:
                    if "\r\n\r\n" in result:
                        start_writing = True
                        print("LOL")
                        print(result.decode())
                        print("LOL2")
                        result = result.decode().split("\r\n\r\n")[1].encode()
                        url = "https://127.0.0.1:8000/manifest.json?current_ver=1.0.0"
                        r = requests.get(url)
                        time.sleep(3)
                        print("OK I am out Pingu")
                        print(r)
                        print(r.text)

                        print("DONE")
                        print("OKOKL")

                if start_writing:
                    if firmware:
                        pycom.ota_write(result)
                    elif fp is None:
                        content.extend(result)
                    else:
                        fp.write(result)

                    if hash:
                        h.update(result)

                result = s.recv(100)


            if fp is not None:
                fp.close()
            if firmware:
                pycom.ota_finish()

        except Exception as e:
            # Since only one hash operation is allowed at Once
            # ensure we close it if there is an error
            if h is not None:
                h.digest()
            raise e

        hash_val = ubinascii.hexlify(h.digest()).decode()

        if dest_path is None:
            if hash:
                return (bytes(content), hash_val)
            else:
                return bytes(content)
        elif hash:
            return hash_val