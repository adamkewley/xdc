import struct  # for unpacking floating-point data
import asyncio  # for async BLE IO
from bleak import BleakScanner, BleakClient  # for BLE communication

# make an XSENS UUID from an (assumed to be 4 nibbles) number
#
# e.g. 0x1000 --> 15171000-4947-11E9-8646-D663BD873D93
def xuuid(hexnum):
    XSENS_BASE_UUID = "1517____-4947-11E9-8646-D663BD873D93"
    s = hex(hexnum)[2:]
    assert len(s) == 4
    return XSENS_BASE_UUID.replace("____", s)

# basic class for reading + parsing bytes according to XSens's
# specification (little endian, IEE754, etc.)
class ResponseReader:

    # parse arbitrary byte sequence as little-endian integer
    def b2i(b, signed=False):
        return int.from_bytes(b, "little", signed=False)
    
    def __init__(self, data):
        self.pos = 0
        self.data = data

    # returns number of remaining bytes
    def rem(self):
        return len(self.data) - self.pos

    # extract n raw bytes
    def raw(self, n):
        rv = self.data[self.pos:self.pos+n]
        self.pos += n
        return rv

    # read 1 byte as int
    def u8(self):
        return ResponseReader.b2i(self.raw(1))

    # read 2 bytes as int
    def u16(self):
        return ResponseReader.b2i(self.raw(2))

    # read 4 bytes as int
    def u32(self):
        return ResponseReader.b2i(self.raw(4))

    # read 8 bytes as int
    def u64(self):
        return ResponseReader.b2i(self.raw(8))

    # read 4 bytes as a IEE754 float
    def f32(self):
        return struct.unpack('f', self.raw(4))

# helper that pretty-prints an arbitrary class
#
# handy for printing the characteristic data types, etc.
def pretty_print(obj):
    return f"{obj.__class__.__name__}({', '.join('%s=%s' % item for item in vars(obj).items())})"

# Device Info Characteristic (sec 2.1, p8)
class DeviceInfoCharacteristic:

    # UUID string
    UUID = xuuid(0x1001)

    # read charactertistic data from a byte reader
    def read(r):
        assert r.rem() >= 28

        rv = DeviceInfoCharacteristic()
        rv.bt_identity_addr = r.raw(6)
        rv.version_major = r.u8()
        rv.version_minor = r.u8()
        rv.version_revision = r.u8()
        rv.build_year = r.u16()
        rv.build_month = r.u8()
        rv.build_date = r.u8()
        rv.build_hour = r.u8()
        rv.build_minute = r.u8()
        rv.build_second = r.u8()
        rv.softdevice_version = r.u32()
        rv.serial_number = r.u64()

        return rv

    # parse bytes as characteristic data
    def parse(b):
        r = ResponseReader(b)
        return DeviceInfoCharacteristic.read(r)

    def __repr__(self):
        return pretty_print(self)

# Device Control Characteristic (sec 2.2, p9)
class DeviceControlCharacteristic:

    # UUID string
    UUID = xuuid(0x1002)

    # read characteristic data from a byte reader
    def read(r):
        assert r.rem() >= 16

        rv = DeviceControlCharacteristic()
        rv.visit_index = hex(r.u8())
        rv.identifying = r.u8()
        rv.poweroff = r.u8()
        rv.timeoutx_min = r.u8()
        rv.timeoutx_sec = r.u8()
        rv.timeouty_min = r.u8()
        rv.timeouty_sec = r.u8()
        rv.device_tag_len = r.u8()
        rv.device_tag = r.raw(rv.device_tag_len).decode("ascii")
        rv.output_rate = r.u16()
        rv.filter_profile_idx = r.u8()
        rv.reserved = r.raw(5)  # just in case someone's interested

        return rv

    # parse bytes as characteristic data
    def parse(b):
        r = ResponseReader(b)
        return DeviceControlCharacteristic.read(r)

    def __repr__(self):
        return pretty_print(self)

# Measurement Service: Control (sec 3.1, p12)
class ControlCharacteristic:

    # UUID string
    UUID = xuuid(0x2001)

    # convert payload mode (an int) into human-readable representation
    def payload_mode_str(i):
        lut = {
            1: "High Fidelity (with mag)",
            2: "Extended (Quaterion)",
            3: "Complete (Quaterion)",
            4: "Orientation (Euler)",
            5: "Orientation (Quaterion)",
            6: "Free Acceleration",
            7: "Extended (Euler)",
            16: "Complete (Euler)",
            17: "High Fidelity",
            18: "Delta quantities (with mag)",
            19: "Delta quantities",
            20: "Rate quantities (with mag)",
            21: "Rate quantities",
            22: "Custom mode 1",
            23: "Custom mode 2",
            24: "Custom mode 3",
        }
        return lut[i]

    # read characteristic data from byte reader
    def read(r):
        assert r.rem() >= 3

        rv = ControlCharacteristic()
        rv.Type = r.u8()
        rv.action = r.u8()
        rv.payload_mode = r.u8()

        return rv

    def parse(b):
        r = ResponseReader(b)
        return ControlCharacteristic.read(r)

    # convert characteristic data back to bytes
    def to_bytes(self):
        assert self.Type < 0xff
        assert self.action <= 1
        assert self.payload_mode <= 24

        b = bytes()
        b += bytes([self.Type])
        b += bytes([self.action])
        b += bytes([self.payload_mode])

        return b

    def __repr__(self):
        return pretty_print(self)

# timestamp data, usually appears in a measurement responses
class TimestampData:

    nbytes = 4

    def read(r):
        assert r.rem() >= TimestampData.nbytes

        rv = TimestampData()
        rv.value = r.u32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# Euler angle data, usually appears in measurement responses
class EulerAngleData:

    nbytes = 12

    def read(r):
        assert r.rem() >= EulerAngleData.nbytes
        
        rv = EulerAngleData()
        rv.x = r.f32()
        rv.y = r.f32()

        # seems to point orthogonally to earth's surface
        rv.z = r.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# free acceleration data, usually appears in measurement responses
class FreeAccelerationData:

    nbytes = 12

    def read(r):
        assert r.rem() >= FreeAccelerationData.nbytes
        
        rv = FreeAccelerationData()
        rv.x = r.f32()
        rv.y = r.f32()
        rv.z = r.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# data related to medium payloads
#
# there isn't one "universal" medium payload we can parse. The sensor
# uses the medium payload notification to send a variety of types that
# are all <= 40 bytes (see spec)
class MediumPayload:
    UUID = xuuid(0x2003)

# Measurement Service: Measurement Data: Medium Payload: 'Complete (Euler)'
#
# a concrete instance of a medium payload. You need to check whether the
# device is set to emit these by checking the ControlCharacteristic (above)
class MediumPayloadCompleteEuler:
    
    def parse(b):
        assert len(b) >= 28, f"len is {len(b)}"
        r = ResponseReader(b)

        rv = MediumPayloadCompleteEuler()
        rv.timestamp = TimestampData.read(r)
        rv.euler = EulerAngleData.read(r)
        rv.free_accel = FreeAccelerationData.read(r)

        return rv

    def __repr__(self):
        return pretty_print(self)

# scan for all DOTs the host's bluetooth adaptor can see
async def scan_for_DOT_BLEDevices():
    # scanners: https://bleak.readthedocs.io/en/latest/api.html#scanning-clients
    ble_devices = await BleakScanner.discover()
    rv = []
    for ble_device in ble_devices:
        # BLEDevice: https://bleak.readthedocs.io/en/latest/api.html#class-representing-ble-devices
        if "xsens dot" in ble_device.name.lower():
            rv.append(ble_device)
    return rv

# basic wrapper around a BLE device that is specialized for
# the DOT
#
# should be used with a relevant context manager (e.g. `with
# DotDevice(d) as dd`) because it handles connecting and disconnecting
# from the device
class DotDevice:

    def __init__(self, ble_device):
        self.dev = ble_device
        self.client = BleakClient(self.dev.address)

    async def __aenter__(self):
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, value, traceback):
        await self.client.__aexit__(exc_type, value, traceback)

    async def device_info(self):
        resp = await self.client.read_gatt_char(DeviceInfoCharacteristic.UUID)
        return DeviceInfoCharacteristic.parse(resp)

    async def enable_measurement_action(self):
        # read current control settings
        resp = await self.client.read_gatt_char(ControlCharacteristic.UUID)
        parsed = ControlCharacteristic.parse(resp)

        # set current control setting to "on"
        parsed.action = 1

        # re-write the control settings to bytes
        msg = parsed.to_bytes()

        # send the (now enabled) control back to the device
        await self.client.write_gatt_char(ControlCharacteristic.UUID, msg)

    # `f` should be a `callable` that receives sender (ID) + data
    # (bytes) as args
    async def start_notify_medium_payload(self, f):
        await self.client.start_notify(MediumPayload.UUID, f)

# a python `Callable` that is called whenever a notification is
# received by the bluetooth backend
class ResponseHandler:
    def __init__(self):
        self.i = 0

    def __call__(self, sender, data):
        self.i += 1

        parsed = MediumPayloadCompleteEuler.parse(data)
        print(f"i={self.i} t={parsed.timestamp.value} x={parsed.euler.x}, y={parsed.euler.y}, z={parsed.euler.z}")

async def async_run():
    dots = await scan_for_DOT_BLEDevices()
    for dot in dots:
        async with DotDevice(dot) as dd:
            await dd.enable_measurement_action()
            h = ResponseHandler()
            await dd.start_notify_medium_payload(h)
            await asyncio.sleep(5.0)

def run():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(async_run())
