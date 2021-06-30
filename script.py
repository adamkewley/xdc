import time
import struct
import asyncio
from bleak import BleakScanner, BleakClient

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

# Measurement Service: Measurement Data: Medium Payload: 'Complete (Euler)'
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

characteristics = [
    DeviceInfoCharacteristic,
    DeviceControlCharacteristic,
    ControlCharacteristic,
]

medium_payload_len_chr = xuuid(0x2003)

async def find_dots():
    # see: https://bleak.readthedocs.io/en/latest/scanning.html
    devices = await BleakScanner.discover()
    rv = []
    for d in devices:
        if "xsens dot" in d.name.lower():
            # d is BLEDevice: https://bleak.readthedocs.io/en/latest/api.html#bleak.backends.device.BLEDevice
            rv.append(d)
    return rv

def on_measurement_payload(sender, data):
    parsed = MediumPayloadCompleteEuler.parse(data)
    print(f"t={parsed.timestamp.value} x={parsed.euler.x}, y={parsed.euler.y}, z={parsed.euler.z}")

# print "Device Info Characteristic" (sec 2.1, p8)
async def print_dot_config(addr):
    async with BleakClient(addr) as client:
        svcs = await client.get_services()
        for svc in svcs:
            print(svc)
        
        for klass in characteristics:
            print(klass.UUID)
            rv = await client.read_gatt_char(klass.UUID)
            print(len(rv))
            print(rv)
            print(klass.parse(rv))

        # enable notifications
        cur_control_chr = ControlCharacteristic.parse(await client.read_gatt_char(ControlCharacteristic.UUID))
        cur_control_chr.action = 1
        await client.write_gatt_char(ControlCharacteristic.UUID, cur_control_chr.to_bytes())       
        

        await client.start_notify(medium_payload_len_chr, on_measurement_payload)
        await asyncio.sleep(5.0)

async def print_dots():
    dots = await find_dots()
    for dot in dots:
        await print_dot_config(dot.address)

def run():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(print_dots())
