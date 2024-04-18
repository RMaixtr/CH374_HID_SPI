import threading
import time
import sys
import os
import inspect
import ctypes
import traceback
import zlib
import zipfile
import spidev

USB_INT = {'EP0_SETUP': 0x0C, 'EP0_OUT': 0x00, 'EP0_IN': 0x08, 'EP1_OUT': 0x01, 'EP1_IN': 0x09, 'EP2_OUT': 0x02,
           'EP2_IN': 0x0A}
MyDevDescr = [0x12, 0x01, 0x10, 0x01, 0x00, 0x00, 0x00, 0x08,
              0x86, 0x1A, 0xE0, 0xE6, 0x00, 0x00, 0x01, 0x02,
              0x00, 0x01]
MyCfgDescr = [0x09, 0x02, 0x29, 0x00, 0x01, 0x01, 0x04, 0xA0, 0x23,
              0x09, 0x04, 0x00, 0x00, 0x02, 0x03, 0x00, 0x00, 0x05,
              0x09, 0x21, 0x00, 0x01, 0x00, 0x01, 0x22, 0x22, 0x00,
              0x07, 0x05, 0x82, 0x03, 64, 0x00, 0x01,
              0x07, 0x05, 0x02, 0x03, 64, 0x00, 0x01, ]
HIDRepDesc = [0x06, 0x00, 0xff, 0x09, 0x01, 0xa1, 0x01, 0x09, 0x02, 0x15, 0x00,
              0x26, 0xFF, 0x00, 0x75, 0x08, 0x95, 0x40, 0x81, 0x06, 0x09, 0x02, 0x15, 0x00,
              0x26, 0xFF, 0x00, 0x75, 0x08, 0x95, 0x40, 0x91, 0x06, 0xC0]
MyLangDescr = [0x04, 0x03, 0x09, 0x04]
MyManuInfo = [0x0E, 0x03, 'C', 0, 'o', 0, 'c', 0, 'o', 0, 'p', 0, 'i', 0]
MyProdInfo = [0x0E, 0x03, 'C', 0, 'o', 0, 'c', 0, 'o', 0, 'p', 0, 'i',
              0]  # [0x0C, 0x03, 'C', 0, 'H', 0, '3', 0, '7', 0, '4', 0]
SetupReq = 0
SetupLen = 0
pDescr = 0
UsbConfig = 0
data = []


class CH374(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)
        self.spi = spidev.SpiDev()
        self.state = None
        self.timeout = 1
        self.loopflag = True
        self.datacallback = []
        self.sendendcallback = []

        self.slaverunflag = False
        self.runthread = None
        self.writeflag = False

        self.getflag = False
        self.getcontflag = False
        self.getlen = 0
        self.getcrc = b''
        self.getcont = 0
        self.zipfile = ''
        self.socfile = ''

        self.gettime = 0
        self.init()

    def __del__(self):
        self.close()

    def close(self):
        self.loopflag = False
        self.join()
        self.spi.close()

    def init(self, timeout=1):
        self.spi.open(1, 0)
        self.spi.max_speed_hz = 500000
        self.spi.mode = 3
        self.Init374Device()
        self.timeout = timeout

        self.start()

    def run(self):
        while self.loopflag:
            if self.Query374Interrupt():
                self.USB_DeviceInterrupt()
            time.sleep(0.0005)

    def USB_DeviceInterrupt(self):
        global pDescr, SetupReq, SetupLen, UsbConfig, data
        s = self.Read374Byte(0x09)
        l = 0
        UserEp2Buf = [1, 2, 3, 4, 5, 6, 7, 8]
        if s & 0x02:  # USB总线复位
            self.Write374Byte(0x08, 0x00)
            self.Write374Byte(0x0C, 0x0E)
            self.Write374Byte(0x0D, 0x0E)
            self.Write374Byte(0x0E, 0x02)
            self.Write374Byte(0x09, 0x10 | 0x02)
        elif s & 0x01:
            s = self.Read374Byte(0x0A)
            if s & 0x0F == USB_INT['EP2_OUT']:
                if s & 0x10:
                    buf = self.Read374Block(0xC0, 64)
                    # print(buf)
                    # and all(byte in b'0123456789abcdef' for byte in buf[buf[0]-7:buf[0]+1])
                    if self.getflag and self.getcontflag:
                        self.getcont += buf[0]
                        with open(self.zipfile, "ab") as file:
                            file.write(bytes(buf[1:buf[0] + 1]))
                        if self.getcont == self.getlen and crc32_file(self.zipfile) == self.getcrc:
                            self.getflag = False
                            self.getcontflag = False
                            self.write(b'\xff\xff' + int_to_bytes(self.getlen) + self.getcrc)
                            self.getcont = 0
                            decompress_file(self.zipfile, self.socfile)
                            os.remove(self.zipfile)
                            print(time.time() - self.gettime)
                    elif buf[1] == 0xff and buf[2] == 0xff:
                        bytes_buf = bytes(buf[1:buf[0] + 1])
                        # print(bytes_buf)
                        if self.getflag and not self.getcontflag:
                            self.getcontflag = True
                            if bytes_buf[2] == 0xf0:
                                self.getcont = 0
                                with open(self.zipfile, "wb") as file:
                                    file.truncate(0)
                            elif bytes_buf[2] == 0xff:
                                self.getflag = False
                                self.getcontflag = False
                                self.getcont = 0
                            if buf[0] > 3:
                                self.getcont += buf[0] - 3
                                with open(self.zipfile, "ab") as file:
                                    file.write(bytes_buf[3:])
                                if self.getcont == self.getlen and crc32_file(self.zipfile) == self.getcrc:
                                    self.getflag = False
                                    self.getcontflag = False
                                    self.write(b'\xff\xff' + int_to_bytes(self.getlen) + self.getcrc)
                                    self.getcont = 0
                                    decompress_file(self.zipfile, self.socfile)
                                    os.remove(self.zipfile)
                                    print(time.time() - self.gettime)
                        
                        elif bytes_buf[2] == b'\x10':
                            runfile = buf[3:buf[0] + 1]
                            if not self.slaverunflag:
                                self.runthread = threading.Thread(target=self.run_file, args=(runfile,))
                                self.slaverunflag = True
                                self.runthread.start()
                            else:
                                self.stop_thread(self.runthread)
                                self.runthread = threading.Thread(target=self.run_file, args=(runfile,))
                                self.runthread.start()
                        elif bytes_buf[2] == b'\x11':
                            if self.slaverunflag:
                                self.stop_thread(self.runthread)
                                self.slaverunflag = False
                            self.write(b'\xff\xff\x1f')
                            sys.stdout = sys.__stdout__
                        elif bytes_buf[2] == b'\xff':
                            self.getflag = False
                            self.getcontflag = False
                            self.getcont = 0
                        elif buf[0] > 16 and not self.getflag:
                            self.parse_file_transfer(bytes_buf)
                    else:
                        if self.datacallback:
                            for call in self.datacallback:
                                call(self, data)
                    self.Write374Byte(0x0E, ((self.Read374Byte(0x0E)) & ~ 0x03 | 0x00) ^ 0x80)  # 0x30

            elif s & 0x0F == USB_INT['EP2_IN']:
                
                if self.writeflag:
                    print('in')
                    self.writeflag = False
                    self.Write374Byte(0x0E, ((self.Read374Byte(0x0E)) & ~ 0x03 | 0x00) ^ 0x40)
                    
                else:
                    self.Write374Byte(0x0E, ((self.Read374Byte(0x0E)) & ~ 0x03 | 0x02) ^ 0x40)
                # a = [0, 1, 2, 3, 4, 5, 6, 7]
                # self.Write374Block(0x40, a)
                # self.Write374Byte(0x0B, 64)
                # self.Write374Byte(0x0E, ((self.Read374Byte(0x0E)) & ~ 0x03 | 0x00) ^ 0x40)

            elif s & 0x0F == USB_INT['EP0_SETUP']:
                l = self.Read374Byte(0x0B)
                if l == 8:
                    SetupReqBuf = self.Read374Block(0x28, l)
                    # print([0] + SetupReqBuf)
                    SetupLen = SetupReqBuf[-2]
                    if SetupReqBuf[-1] or SetupLen > 0x7F:
                        SetupLen = 0x7F
                    l = 0
                    if (SetupReqBuf[0] & 0x60) != 0x00:
                        if SetupReqBuf[1] == 1:
                            pDescr = 0
                            data = UserEp2Buf
                            if SetupLen >= 8:
                                l = 8
                            else:
                                l = SetupLen
                        if SetupLen > l:
                            SetupLen = l
                        l = 0x08 if SetupLen >= 0x08 else SetupLen
                        self.Write374Block(0x20, data[pDescr:pDescr + l])
                        SetupLen -= l
                        pDescr += l
                    else:
                        SetupReq = SetupReqBuf[1]
                        if SetupReq == 0x06:
                            if SetupReqBuf[3] == 1:  # 设备描述
                                pDescr = 0
                                data = MyDevDescr
                                l = len(data)
                            elif SetupReqBuf[3] == 2:  # 配置描述
                                pDescr = 0
                                data = MyCfgDescr
                                l = len(data)
                            elif SetupReqBuf[3] == 3:
                                if SetupReqBuf[2] == 0:  # 语言描述
                                    pDescr = 0
                                    data = MyLangDescr
                                    l = len(data)
                                elif SetupReqBuf[2] == 1:  # 厂家信息
                                    pDescr = 0
                                    data = MyManuInfo
                                    l = len(data)
                                elif SetupReqBuf[2] == 2:  # 产品信息
                                    pDescr = 0
                                    data = MyProdInfo
                                    l = len(data)
                                else:
                                    l = 0xff
                            elif SetupReqBuf[3] == 0x22:
                                pDescr = 0
                                data = HIDRepDesc
                                l = len(data)
                            else:
                                l = 0xff
                            if SetupLen > l:
                                SetupLen = l
                            l = 0x08 if SetupLen >= 0x08 else SetupLen
                            self.Write374Block(0x20, data[pDescr:pDescr + l])
                            SetupLen -= l
                            pDescr += l
                        elif SetupReq == 0x05:
                            SetupLen = SetupReqBuf[2]
                        elif SetupReq == 0x08:
                            self.Write374Byte(0x20, UsbConfig)
                            if SetupLen >= 1:
                                l = 1
                        elif SetupReq == 0x09:
                            UsbConfig = SetupReqBuf[2]
                        elif SetupReq == 0x01:
                            if (SetupReqBuf[0] & 0x1F) == 0x02:
                                if SetupReqBuf[4] == 0x82:
                                    self.Write374Byte(0x0E, ((self.Read374Byte(0x0E)) & ~ 0x03 | 0x02))
                                elif SetupReqBuf[4] == 0x02:
                                    self.Write374Byte(0x0E, ((self.Read374Byte(0x0E)) & ~ 0x30 | 0x00))
                                elif SetupReqBuf[4] == 0x81:
                                    self.Write374Byte(0x0D, ((self.Read374Byte(0x0D)) & ~ 0x0F | 0x0E))
                                elif SetupReqBuf[4] == 0x01:
                                    self.Write374Byte(0x0D, ((self.Read374Byte(0x0D)) & ~ 0x30 | 0x00))
                                else:
                                    l = 0xFF
                            else:
                                l = 0xFF
                        elif SetupReq == 0x0A:
                            self.Write374Byte(0x20, 0)
                            if SetupLen >= 1:
                                l = 1
                        elif SetupReq == 0x00:
                            self.Write374Byte(0x20, 0)
                            self.Write374Byte(0x20 + 1, 0)
                            if SetupLen >= 2:
                                l = 2
                            else:
                                l = SetupLen
                        else:
                            l = 0xFF
                else:
                    l = 0xFF
                if l == 0xFF:
                    self.Write374Byte(0x0C, ((0 & ~ 0x0F | 0x0F) & ~ 0x30 | 0x30))
                elif l <= 0x08:
                    self.Write374Byte(0x0C, (((self.Read374Byte(0x0C)) & ~ 0x30 | 0x00) & ~ 0x0F | l & 0x0F) | 0x40)
                else:
                    self.Write374Byte(0x0C, (((self.Read374Byte(0x0C)) & ~ 0x30 | 0x00) & ~ 0x0F | 0x0E) | 0x80)
            elif s & 0x0F == USB_INT['EP0_IN']:
                if SetupReq == 0x06:
                    l = 0x08 if SetupLen >= 0x08 else SetupLen
                    self.Write374Block(0x20, data[pDescr:pDescr + l])
                    SetupLen -= l
                    pDescr += l
                    self.Write374Byte(0x0C, ((self.Read374Byte(0x0C)) & ~ 0x0F | l & 0x0F) ^ 0x40)
                elif SetupReq == 0x05:
                    self.Write374Byte(0x08, SetupLen)
                else:
                    self.Write374Byte(0x0C, (0 & ~ 0x0F | 0x0E))
            elif s & 0x0F == USB_INT['EP0_OUT']:
                if SetupReq == 0x06:
                    pass
                else:
                    self.Write374Byte(0x0C, (0 & ~ 0x0F | 0x0E))
            self.Write374Byte(0x09, 0x10 | 0x01)
        elif s & 0x04:
            self.Write374Byte(0x09, 0x10 | 0x04)
            self.Write374Byte(0x05, self.Read374Byte(0x05) | 0x01)
        elif s & 0x08:
            self.Write374Byte(0x09, 0x10 | 0x08)
        else:
            self.Write374Byte(0x09, 0x10 | 0x0F)

    def parse_file_transfer(self, data):
        self.getflag = True
        self.getcrc = data[-8:]
        self.getlen = bytes_to_int(data[-14:-8])
        self.getcont = 0
        self.zipfile = os.path.join(os.getcwd(), 'bletemp',
                                    os.path.basename((data[2:-14] + b'.zip').decode('utf-8')))
        self.socfile = os.path.dirname(os.path.abspath(data[2:-14].decode('utf-8')))
        self.gettime = time.time()
        if os.path.exists(self.zipfile):
            with open(self.zipfile, 'rb') as file:
                filedata = file.read()
            cmpcrc = crc32(filedata)
            if self.getlen == len(filedata) and self.getcrc == cmpcrc:
                self.write(b'\xff\xff' + data[-14:])
            elif self.getlen > len(filedata) > 0:
                redata = b'\xff\xff' + int_to_bytes(len(filedata)) + cmpcrc
                self.write(redata)
                self.getcont = len(filedata)
            else:
                self.write(b'\xff\xff00000000000000')
                self.getcont = 0
        else:
            if not os.path.exists(os.path.dirname(self.zipfile)):
                os.makedirs(os.path.dirname(self.zipfile))
            self.write(b'\xff\xff00000000000000')
            self.getcont = 0

    def write(self, lis):
        if self.writeflag:
            return False
        else:
            lis = list(lis)
            lis += [0] * (64 - len(lis))
            self.Write374Block(0x40, lis)
            self.Write374Byte(0x0B, 64)
            self.writeflag = True
            return True

    def get_state(self):
        return self.state

    def add_data_callback(self, function):
        self.datacallback.append(function)

    def add_sendend_callback(self, function):
        self.sendendcallback.append(function)

    def del_data_callback(self, function=None):
        self.datacallback.remove(function) if function else self.datacallback.pop()

    def del_sendend_callback(self, function=None):
        self.sendendcallback.remove(function) if function else self.sendendcallback.pop()

    def Read374Byte(self, mAddr):
        return self.spi.xfer2([mAddr, 0xC0, 0xFF])[-1]

    def Write374Byte(self, mAddr, mData):
        lis = [mAddr, 0x80]
        lis.append(mData)
        return self.spi.xfer2(lis)

    def Read374Block(self, mAddr, mLen):
        lis = [mAddr, 0xC0]
        lis.extend([0xFF] * mLen)
        return self.spi.xfer2(lis)[2:]

    def Write374Block(self, mAddr, mList):
        mList = convert_str_to_ascii(mList)
        lis = [mAddr, 0x80]
        lis.extend(mList)
        return self.spi.xfer2(lis)

    def Query374Interrupt(self):
        return self.Read374Byte(0x09) & 0x0F if 1 else 0

    def Init374Device(self):
        self.Write374Byte(0x08, 0x00)
        self.Write374Byte(0x0C, 0x0E)
        self.Write374Byte(0x0D, 0x0E)
        self.Write374Byte(0x0E, 0x02)
        self.Write374Byte(0x09, 0x10 | 0x0F)
        self.Write374Byte(0x07, 0x01 | 0x02 | 0x04)
        self.Write374Byte(0x05, 0x40)
        self.Write374Byte(0x06, 0x01 | 0x02)

    def run_code(self, code):
        # sys.stdout = self
        try:
            exec(code, globals(), globals())
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            trace = traceback.extract_tb(exc_traceback)
            _, lineno, _, _ = trace[-1]
            traceback_details = {
                'lineno': lineno,
                'type': exc_type.__name__,
                'message': str(exc_value),
            }
            # self.write(str(traceback_details))
            time.sleep(1)
        # self.restore()
        # self.write(b'\xff\xff\x1f')
        self.slaverunflag = False
        # sys.stdout = sys.__stdout__

    def run_file(self, file_path):
        os.path.exists(file_path.decode('utf-8'))
        with open(file_path, 'r') as file:
            file_content = file.read()
        file.close()
        self.run_code(file_content)

    def _async_raise(self, tid, exctype):
        """raises the exception, performs cleanup if needed"""
        tid = ctypes.c_long(tid)
        if not inspect.isclass(exctype):
            exctype = type(exctype)
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(exctype))
        if res == 0:
            raise ValueError("invalid thread id")
        elif res != 1:
            # """if it returns a number greater than one, you're in trouble,
            # and you should call it again with exc=NULL to revert the effect"""
            ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
            raise SystemError("PyThreadState_SetAsyncExc failed")

    def stop_thread(self, thread):
        self._async_raise(thread.ident, SystemExit)


CH374 = CH374()


def int_to_bytes(num):
    array = bytearray(6)
    for i in range(5, -1, -1):
        array[i] = num % 256
        num >>= 8
    return array


def bytes_to_int(array):
    num = 0
    for i in range(len(array)):
        num += array[i] << ((len(array) - 1 - i) * 8)
    return num


def crc32(datas):
    return hex(zlib.crc32(datas))[2:].zfill(8).encode()


def crc32_file(file_path):
    with open(file_path, 'rb') as file:
        file_data = file.read()
    return crc32(file_data)


def compress_file(filename, output_filename):
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(filename, os.path.basename(filename))


def decompress_file(zip_filename, output_dir):
    with zipfile.ZipFile(zip_filename, 'r') as zipf:
        zipf.extractall(output_dir)


def convert_str_to_ascii(lst):
    result = []
    for item in lst:
        if isinstance(item, str):
            ascii_chars = [ord(char) for char in item]
            result.extend(ascii_chars)
        else:
            result.append(item)
    return result
