import struct  # for unpacking floating-point data
import asyncio  # for async BLE IO
from bleak import BleakScanner, BleakClient  # for BLE communication

# helper that pretty-prints an arbitrary class
#
# handy for printing the characteristic data types, etc.
def pretty_print(obj):
    return f"{obj.__class__.__name__}({', '.join('%s=%s' % item for item in vars(obj).items())})"

# make an XSENS UUID from an (assumed to be 4 nibbles) number
#
# from BLE spec, sec 1.1: "Base UUID"
#
# e.g. 0x1000 --> 15171000-4947-11E9-8646-D663BD873D93
def xuuid(hexnum):
    XSENS_BASE_UUID = "1517xxxx-4947-11E9-8646-D663BD873D93"
    s = hex(hexnum)[2:]
    assert len(s) == 4
    return XSENS_BASE_UUID.replace("xxxx", s)

# the XSens DOT provides BLE services with the following prefixes on the
# UUID:
#
# 0x1000 (e.g. 15171000-4947-...): configuration service
# 0x2000                         : measurement service
# 0x3000                         : charging status/battery level service
# 0x7000                         : message service

# helper class for reading + parsing bytes according to XSens's
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

# Device Info Characteristic (sec 2.1, p8 in the BLE spec)
class DeviceInfoCharacteristic:
    UUID = xuuid(0x1001)

    # read charactertistic data from a byte reader
    def read(r):
        assert r.rem() >= 34

        rv = DeviceInfoCharacteristic()
        rv.address = r.raw(6)
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
        rv.short_product_code = r.raw(6)

        return rv

    # parse bytes as characteristic data
    def parse(b):
        r = ResponseReader(b)
        return DeviceInfoCharacteristic.read(r)

    def __repr__(self):
        return pretty_print(self)

# Device Control Characteristic (sec 2.2, p9 in the BLE spec)
class DeviceControlCharacteristic:
    UUID = xuuid(0x1002)

    # read characteristic data from a byte reader
    def read(r):
        assert r.rem() >= 16

        rv = DeviceControlCharacteristic()
        rv.visit_index = r.u8()
        rv.identifying = r.u8()
        rv.poweroff = r.u8()
        rv.timeoutx_min = r.u8()
        rv.timeoutx_sec = r.u8()
        rv.timeouty_min = r.u8()
        rv.timeouty_sec = r.u8()
        rv.device_tag_len = r.u8()
        rv.device_tag = r.raw(16)
        rv.output_rate = r.u16()
        rv.filter_profile_idx = r.u8()
        rv.reserved = r.raw(5)  # just in case someone's interested

        return rv

    # parse bytes as characteristic data
    def parse(b):
        r = ResponseReader(b)
        return DeviceControlCharacteristic.read(r)

    # write characteristic as bytes
    def to_bytes(self):
        rv = bytearray()
        rv += self.visit_index.to_bytes(1, "little")
        rv += self.identifying.to_bytes(1, "little")
        rv += self.poweroff.to_bytes(1, "little")
        rv += self.timeoutx_min.to_bytes(1, "little")
        rv += self.timeoutx_sec.to_bytes(1, "little")
        rv += self.timeouty_min.to_bytes(1, "little")
        rv += self.timeouty_sec.to_bytes(1, "little")
        rv += self.device_tag_len.to_bytes(1, "little")
        rv += self.device_tag
        rv += self.output_rate.to_bytes(2, "little")
        rv += self.filter_profile_idx.to_bytes(1, "little")
        rv += self.reserved
        return rv

    def __repr__(self):
        return pretty_print(self)

# Device Report Characteristic (sec 2.3, p10 in the BLE spec)
class DeviceReportCharacteristic:
    UUID = xuuid(0x1004)

    # read characteristic data from a byte reader
    def read(r):
        assert r.rem() == 36

        rv = DeviceReportCharacteristic()
        rv.typeid = r.u8()
        if rv.typeid == 5:
            rv.length = r.u8()
            if rv.length == 4:
                rv.timestamp = r.u32()
            elif rv.length == 8:
                rv.timestamp = r.u64()
        rv.unused = r.raw(r.rem())

        return rv

    # parse bytes as characteristic data
    def parse(b):
        r = ResponseReader(b)
        return DeviceReportCharacteristic.read(r)

    def __repr__(self):
        return pretty_print(self)

# Measurement Service: Control (sec 3.1, p12 in the BLE spec)
class ControlCharacteristic:
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

    # parse bytes as characteristic data
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

# data for long-payload measurements
#
# the DOT can emit data in long (63-byte), medium (40-byte), and short (20-byte) lengths.
# What those bytes parse out to depends on the payload mode (see "Measurement Service Control
# Characteristic") is set to.
class LongPayloadCharacteristic:
    UUID = xuuid(0x2002)

# data for medium-payload measurements
#
# the DOT can emit data in long (63-byte), medium (40-byte), and short (20-byte) lengths.
# What those bytes parse out to depends on the payload mode (see "Measurement Service Control
# Characteristic") is set to.
class MediumPayloadCharacteristic:
    UUID = xuuid(0x2003)

# data for short-payload measurements
#
# the DOT can emit data in long (63-byte), medium (40-byte), and short (20-byte) lengths.
# What those bytes parse out to depends on the payload mode (see "Measurement Service Control
# Characteristic") is set to.
class ShortPayloadCharacteristic:
    UUID = xuuid(0x2004)

# the next bunch of classes are parsers etc. for the wide variety of measurement structs
# that the measurement service can emit

# measurement data (sec. 3.5 in BLE spec): timestamp: "Timestamp of the sensor in microseconds"
class Timestamp:
    size = 4

    def read(reader):
        assert reader.rem() >= Timestamp.size

        rv = Timestamp()
        rv.microseconds = reader.u32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5 in BLE spec): quaternion: "The orientation expressed as a quaternion"
class Quaternion:
    size = 16

    def read(reader):
        assert reader.rem() >= Quaternion.size

        rv = Quaternion()
        rv.w = reader.f32()
        rv.x = reader.f32()
        rv.y = reader.f32()
        rv.z = reader.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5 in BLE spec): euler angles: "The orientation expressed as Euler angles, degree"
class EulerAngles:
    size = 12

    def read(reader):
        assert reader.rem() >= EulerAngles.size

        rv = EulerAngles()
        rv.x = reader.f32()
        rv.y = reader.f32()
        rv.z = reader.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5 in the BLE spec): free acceleration: "Acceleration in local earth coordinate and the local gravity is deducted, m/s^2"
class FreeAcceleration:
    size = 12

    def read(reader):
        assert reader.rem() >= FreeAcceleration.size

        rv = FreeAcceleration()
        rv.x = reader.f32()
        rv.y = reader.f32()
        rv.z = reader.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5 in BLE spec): dq: "Orientation change during a time interval"
class Dq:
    size = 16

    def read(reader):
        assert reader.rem() >= Dq.size

        rv = Dq()
        rv.w = reader.f32()
        rv.x = reader.f32()
        rv.y = reader.f32()
        rv.z = reader.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5 in the BLE spec): dv: "Velocity change during a time interval, m/s"
class Dv:
    size = 12

    def read(reader):
        assert reader.rem() >= Dv.size

        rv = Dv()
        dv.x = reader.f32()
        dv.y = reader.f32()
        dv.z = reader.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5 in the BLE spec): Acceleration: "Calibrated acceleration in sensor coordinate, m/s^2"
class Acceleration:
    size = 12

    def read(reader):
        assert reader.rem() >= Acceleration.size

        rv = Acceleration()
        rv.x = reader.f32()
        rv.y = reader.f32()
        rv.z = reader.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5 in the BLE spec): Angular Velocity: "Rate of turn in sensor coordinate, dps"
class AngularVelocity:
    size = 12

    def read(reader):
        assert reader.rem() >= AngularVelocity.size

        rv = AngularVelocity()
        rv.x = reader.f32()
        rv.y = reader.f32()
        rv.z = reader.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5 in the BLE spec): Magnetic Field: "Magnetic field in the sensor coordinate, a.u."
class MagneticField:
    size = 6

    def read(reader):
        assert reader.rem() >= MagneticField.size

        rv = MagneticField()
        rv.x = reader.raw(2)
        rv.y = reader.raw(2)
        rv.z = reader.raw(2)

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5 in the BLE spec): Status: "See section 3.5.1 of the BLE spec"
class Status:
    size = 2

    def read(reader):
        assert reader.rem() >= Status.size

        rv = Status()
        rv.value = reader.u16()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5. in the BLE spec): ClipCountAcc: "Count of ClipAcc in status"
class ClipCountAcc:
    size = 1

    def read(reader):
        assert reader.rem() >= ClipCountAcc.size

        rv = ClipCountAcc()
        rv.value = reader.u8()

        return rv

    def __repr__(self):
        return pretty_print(self)

# measurement data (sec. 3.5. in the BLE spec): ClipCountGyr: "Count of ClipGyr in status"
class ClipCountGyr:
    size = 1

    def read(reader):
        assert reader.rem() >= ClipCountGyr.size

        rv = ClipCountGyr()
        rv.value = reader.u8()

        return rv

    def __repr__(self):
        return pretty_print(self)

class LongPayloadCustomMode4:
    size = 51

    # no parser: it's not officially supported by XSens

class MediumPayloadExtendedQuaternion:
    size = 36

    def read(reader):
        assert reader.rem() >= MediumPayloadExtendedQuaternion.size

        rv = MediumPayloadExtendedQuaternion()
        rv.timestamp = Timestamp.read(reader)
        rv.quaternion = Quaternion.read(reader)
        rv.free_acceleration = FreeAcceleration.read(reader)
        rv.status = Status.read(reader)
        rv.clip_count_acc = ClipCountAcc.read(reader)
        rv.clip_count_gyr = ClipCountGyr.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class MediumPayloadCompleteQuaternion:
    size = 32

    def read(reader):
        assert reader.rem() >= MediumPayloadCompleteQuaternion.size

        rv = MediumPayloadCompleteQuaternion()
        rv.timestamp = Timestamp.read(reader)
        rv.quaternion = Quaternion.read(reader)
        rv.free_acceleration = FreeAcceleration.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class MediumPayloadExtendedEuler:
    size = 32

    def read(reader):
        assert reader.rem() >= MediumPayloadExtendedEuler.size

        rv = MediumPayloadExtendedEuler()
        rv.timestamp = Timestamp.read(reader)
        rv.euler = EulerAngles.read(reader)
        rv.free_acceleration = FreeAcceleration.read(reader)
        rv.status = Status.read(reader)
        rv.clip_count_acc = ClipCountAcc.read(reader)
        rv.clip_count_gyr = ClipCountGyr.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class MediumPayloadCompleteEuler:
    size = 28

    def read(reader):
        assert reader.rem() >= MediumPayloadCompleteEuler.size

        rv = MediumPayloadCompleteEuler()
        rv.timestamp = Timestamp.read(reader)
        rv.euler = EulerAngles.read(reader)
        rv.free_acceleration = FreeAcceleration.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class MediumPayloadHighFidelityWithMag:
    size = 35

    # no parser: XSens claims you need to use the SDK to get this

class MediumPayloadHighFidelity:
    size = 29

    # no parser: XSens claims you need to use the SDK to get this

class MediumPayloadDeltaQuantitiesWithMag:
    size = 38

    def read(reader):
        assert reader.rem() >= MediumPayloadDataQuantitiesWithMag.size

        rv = MediumPayloadDeltaQuantitiesWithMag()
        rv.timestamp = Timestamp.read(reader)
        rv.dq = Dq.read(reader)
        rv.dv = Dv.read(reader)
        rv.magnetic_field = MagneticField.read(reader)

        return rv

class MediumPayloadDeltaQuantities:
    size = 32

    def read(reader):
        assert reader.rem() >= MediumPayloadDeltaQuantities.size

        rv = MediumPayloadDeltaQuantities()
        rv.timestamp = Timestamp.read(reader)
        rv.dq = Dq.read(reader)
        rv.dv = Dv.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class MediumPayloadRateQuantitiesWithMag:
    size = 34

    def read(reader):
        assert reader.rem() >= MediumPayloadRateQuantitiesWithMag.size

        rv = MediumPayloadRateQuantitiesWithMag()
        rv.timestamp = Timestamp.read(reader)
        rv.acceleration = Acceleration.read(reader)
        rv.angular_velocity = AngularVelocity.read(reader)
        rv.magnetic_field = MagneticField.read(reader)

    def __repr__(self):
        return pretty_print(self)

class MediumPayloadRateQuantities:
    size = 28

    def read(reader):
        assert reader.rem() >= MediumPayloadRateQuantities.size

        rv = MediumPayloadRateQuantities()
        rv.timestamp = Timestamp.read(reader)
        rv.acceleration = Acceleration.read(reader)
        rv.angular_velocity = AngularVelocity.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class MediumPayloadCustomMode1:
    size = 40

    def read(reader):
        assert reader.rem() >= MediumPayloadCustomMode1.size

        rv = MediumPayloadCustomMode1()
        rv.timestamp = Timestamp.read(reader)
        rv.euler = EulerAngles.read(reader)
        rv.free_acceleration = FreeAcceleration.read(reader)
        rv.angular_velocity = AngularVelocity.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class MediumPayloadCustomMode2:
    size = 34

    def read(reader):
        assert reader.rem() >= MediumPayloadCustomMode2.size

        rv = MediumPayloadCustomMode2()
        rv.timestamp = Timestamp.read(reader)
        rv.euler = EulerAngles.read(reader)
        rv.free_acceleration = FreeAcceleration.read(reader)
        rv.magnetic_field = MagneticField.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class MediumPayloadCustomMode3:
    size = 32

    def read(reader):
        assert reader.rem() >= MediumPayloadCustomMode3.size

        rv = MediumPayloadCustomMode3()
        rv.timestamp = Timestamp.read(reader)
        rv.quaternion = Quaternion.read(reader)
        rv.angular_velocity = AngularVelocity.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class ShortPayloadOrientationEuler:
    size = 16

    def read(reader):
        assert reader.rem() >= ShortPayloadOrientationEuler.size

        rv = ShortPayloadOrientationEuler()
        rv.timestamp = Timestamp.read(reader)
        rv.euler = EulerAngles.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class ShortPayloadOrientationQuaternion:
    size = 20

    def read(reader):
        assert reader.rem() >= ShortPayloadOrientationQuaternion.size

        rv = ShortPayloadOrientationQuaternion()
        rv.timestamp = Timestamp.read(reader)
        rv.quaternion = Quaternion.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class ShortPayloadFreeAcceleration:
    size = 16

    def read(reader):
        assert reader.rem() >= ShortPayloadFreeAcceleration.size

        rv = ShortPayloadFreeAcceleration()
        rv.timestamp = Timestamp.read(reader)
        rv.free_acceleration = FreeAcceleration.read(reader)

        return rv

    def __repr__(self):
        return pretty_print(self)

class BatteryCharacteristic:

    UUID = xuuid(0x3001)

    def parse(b):
        assert len(b) == 2

        r = ResponseReader(b)

        rv = BatteryCharacteristic()
        rv.battery_level = r.u8()
        rv.charging_status = r.u8()

        return rv

    def __repr__(self):
        return pretty_print(self)

# lifetime wrapper around a BLE device that is specialized for
# the DOT
#
# this is what resource- and timing-sensitive code should use, because
# it minimizes the number of (re)connections to the device. Procedural
# (esp. synchronous) code using the helper methods (below) will run slower
# because the API has to handle setting up and tearing down a new connection
class Dot:

    # init/enter/exit: connect/disconnect to the DOT

    # init a new `Dot` instance
    #
    # initializes the underlying connection client, but does not connect to
    # the DOT. Use `.connect`/`.disconnect`, or (better) a context manager
    # (`with Dot(ble) as dot`), or (better again) an async context manager
    # (`async with Dot(ble) as dot`) to setup/teardown the connection
    def __init__(self, ble_device):
        self.dev = ble_device
        self.client = BleakClient(self.dev.address)

    # called when entering `async with` blocks
    async def __aenter__(self):
        await self.client.__aenter__()
        return self

    # called when exiting `async with` blocks
    async def __aexit__(self, exc_type, value, traceback):
        await self.client.__aexit__(exc_type, value, traceback)

    # called when entering (synchronous) `with` blocks
    def __enter__(self):
        asyncio.get_event_loop().run_until_complete(self.__aenter__())
        return self

    # called when exiting (synchronous) `with` blocks
    def __exit__(self, exc_type, value, traceback):
        asyncio.get_event_loop().run_until_complete(self.__aexit__(exc_type, value, traceback))

    # manual connection management (handy for manual use in a terminal or something)

    # asynchronously establishes a connection to the DOT
    async def aconnect(self):
        return await self.client.connect()

    # synchronously establishes a connection to the DOT
    def connect(self):
        return asyncio.get_event_loop().run_until_complete(self.aconnect())

    # asynchronously terminates the connection to the DOT
    async def adisconnect(self):
        return await self.client.disconnect()

    # synchronously terminates the connection to the DOT
    def disconnect(self):
        return asyncio.get_event_loop().run_until_complete(self.adisconnect())

    # low-level characteristic accessors

    # asynchronously reads the "Device Info Characteristic" (sec. 2.1 in the BLE spec)
    async def adevice_info_read(self):
        resp = await self.client.read_gatt_char(DeviceInfoCharacteristic.UUID)
        return DeviceInfoCharacteristic.parse(resp)

    # synchronously reads the "Device Info Characteristic" (sec. 2.1 in the BLE spec)
    def device_info_read(self):
        return asyncio.get_event_loop().run_until_complete(self.adevice_info_read())

    # asynchronously reads the "Device Control Characteristic" (sec. 2.2. in the BLE spec)
    async def adevice_control_read(self):
        resp = await self.client.read_gatt_char(DeviceControlCharacteristic.UUID)
        return DeviceControlCharacteristic.parse(resp)

    # synchronously reads the "Device Control Characteristic" (sec. 2.2. in the BLE spec)
    def device_control_read(self):
        return asyncio.get_event_loop().run_until_complete(self.adevice_control_read())

    # asynchronously writes the "Device Control Characteristic" (sec. 2.2. in the BLE spec)
    #
    # arg must be a `DeviceControlCharacteristic` with its fields set to appropriate
    # values (read the BLE spec to see which values are supported)
    async def adevice_control_write(self, device_control_characteristic):
        msg_bytes = device_control_characteristic.to_bytes()
        await self.client.write_gatt_char(DeviceControlCharacteristic.UUID, msg_bytes, True)

    # synchronously writes the "Device Control Characteristic" (sec. 2.2. in the BLE spec)
    #
    # arg must be a `DeviceControlCharacteristic` with its fields set to appropriate
    # values (read the BLE spec to see which values are supported)
    def device_control_write(self, device_control_characteristic):
        asyncio.get_event_loop().run_until_complete(self.adevice_control_write(device_control_characteristic))

    # asynchronously enable notifications from the "Device Report Characteristic" (sec.
    # 2.3 in the BLE spec)
    #
    # once notifications are enabled, `callback` will be called with two arguments:
    # a message ID and the raw message bytes (which can be parsed using
    # `DeviceReportCharacteristic.parse`). Notifications arrive from the DOT whenever
    # a significant event happens (e.g. a button press). See the BLE spec for which
    # events trigger from which actions.
    async def adevice_report_start_notify(self, callback):
        await self.client.start_notify(DeviceReportCharacteristic.UUID, callback)

    # synchronously enable notifications from the "Device Report Characteristic" (sec.
    # 2.3 in the BLE spec)
    #
    # once notifications are enabled, `callback` will be called with two arguments:
    # a message ID and the raw message bytes (which can be parsed using
    # `DeviceReportCharacteristic.parse`). Notifications arrive from the DOT whenever
    # a significant event happens (e.g. a button press). See the BLE spec for which
    # events trigger from which actions.
    def device_report_start_notify(self, callback):
        asyncio.get_event_loop().run_until_complete(self.adevice_report_start_notify(callback))

    # asynchronously disable notifications from the "Device Report Characteristic" (sec.
    # 2.3 in the BLE spec)
    #
    # this disables notifications that were enabled by the `device_report_start_notify`
    # method. After this action completes, the `callback` in the enable call will no longer
    # be called
    async def adevice_report_stop_notify(self):
        await self.client.stop_notify(DeviceReportCharacteristic.UUID)

    # synchronously disable notifications from the "Device Report Characteristic" (sec.
    # 2.3 in the BLE spec)
    #
    # this disables notifications that were enabled by the `device_report_start_notify`
    # method. After this action completes, the `callback` in the enable call will no longer
    # be called
    def device_report_stop_notify(self):
        asyncio.get_event_loop().run_until_complete(self.adevice_report_stop_notify())

    # asynchronously read the "Control Characteristic" (sec. 3.1 in the BLE spec)
    async def acontrol_read(self):
        resp = await self.client.read_gatt_char(ControlCharacteristic.UUID)
        return ControlCharacteristic.parse(resp)

    # asynchronously read the "Control Characteristic" (sec. 3.1 in the BLE spec)
    def control_read(self):
        return asyncio.get_event_loop().run_until_complete(self.acontrol_read())

    async def acontrol_write(self, control_characteristic):
        msg_bytes = control_characteristic.to_bytes()
        await self.client.write_gatt_char(ControlCharacteristic.UUID, msg_bytes)

    def control_write(self, control_characteristic):
        asyncio.get_event_loop().run_until_complete(self.acontrol_write(control_characteristic))

    async def along_payload_start_notify(self, callback):
        await self.client.start_notify(LongPayloadCharacteristic.UUID, callback)

    def long_payload_start_notify(self, callback):
        asyncio.get_event_loop().run_until_complete(self.along_payload_start_notify(callback))

    async def along_payload_stop_notify(self):
        await self.client.stop_notify(LongPayloadCharacteristic.UUID)

    def long_payload_stop_notify(self):
        asyncio.get_event_loop().run_until_complete(self.along_payload_stop_notify())

    async def amedium_payload_start_notify(self, callback):
        await self.client.start_notify(MediumPayloadCharacteristic.UUID, callback)

    def medium_payload_start_notify(self, callback):
        asyncio.get_event_loop().run_until_complete(self.amedium_payload_start_notify(callback))

    async def amedium_payload_stop_notify(self):
        await self.client.stop_notify(MediumPayloadCharacteristic.UUID)

    def medium_payload_stop_notify(self):
        asyncio.get_event_loop().run_until_complete(self.amedium_payload_stop_notify())

    async def ashort_payload_start_notify(self, callback):
        await self.client.start_notify(ShortPayloadCharacteristic.UUID, callback)

    def short_payload_start_notify(self, callback):
        asyncio.get_event_loop().run_until_complete(self.ashort_payload_start_notify(callback))

    async def ashort_payload_stop_notify(self):
        await self.client.stop_notify(ShortPayloadCharacteristic.UUID)

    def short_payload_stop_notify(self):
        asyncio.get_event_loop().run_until_complete(self.ashort_payload_stop_notify())

    # asynchronously read the "Battery Characteristic" (sec. 4.1 in the BLE spec)
    async def abattery_read(self):
        resp = await self.client.read_gatt_char(BatteryCharacteristic.UUID)
        return BatteryCharacteristic.parse(resp)

    # synchronously read the "Battery Characteristic" (sec. 4.1 in the BLE spec)
    def battery_read(self):
        return asyncio.get_event_loop().run_until_complete(self.abattery_read())

    # asynchronously enable battery notifications from the "Battery Characteristic" (see
    # sec. 4.1 in the BLE spec)
    async def abattery_start_notify(self, callback):
        await self.client.start_notify(BatteryCharacteristic.UUID, callback)

    # synchronously enable battery notifications from the "Battery Characteristic" (see
    # sec. 4.1 in the BLE spec)
    def battery_start_notify(self, callback):
        asyncio.get_event_loop().run_until_complete(self.abattery_start_notify(callback))

    # high-level operations

    # asynchronously requests that the DOT identifies itself
    #
    # (from BLE spec sec. 2.2.): The sensor LED will fast blink 8 times and then
    # a short pause in red, lasting for 10 seconds.
    async def aidentify(self):
        dc = await self.adevice_control_read()
        dc.visit_index = 0x01
        dc.identifying = 0x01
        await self.adevice_control_write(dc)

    # synchronously requests that the DOT identifies itself
    #
    # (from BLE spec sec. 2.2.): The sensor LED will fast blink 8 times and then
    # a short pause in red, lasting for 10 seconds.
    def identify(self):
        asyncio.get_event_loop().run_until_complete(self.aidentify())

    # asynchronously requests that the DOT powers itself off
    async def apower_off(self):
        dc = await self.adevice_control_read()
        dc.visit_index = 0x02
        dc.poweroff = dc.poweroff | 0x01
        await self.adevice_control_write(dc)

    # synchronously requests that the DOT powers itself off
    def power_off(self):
        asyncio.get_event_loop().run_until_complete(self.apower_off())

    # asynchronosly requests that the DOT should power itself on when plugged into
    # a USB (e.g. when charging)
    async def aenable_power_on_by_usb_plug_in(self):
        dc = await self.adevice_control_read()
        dc.visit_index = 0x02
        dc.poweroff = dc.poweroff | 0x02
        await self.adevice_control_write(dc)

    # synchronosly requests that the DOT should power itself on when plugged into
    # a USB (e.g. when charging)
    def enable_power_on_by_usb_plug_in(self):
        asyncio.get_event_loop().run_until_complete(self.aenable_power_on_by_usb_plug_in())

    # asynchronously requests that the DOT shouldn't power itself on when plugged into
    # a USB (e.g. when charging)
    async def adisable_power_on_by_usb_plug_in(self):
        dc = await self.adevice_control_read()
        dc.visit_index = 0x02
        dc.poweroff = dc.poweroff & ~(0x02)
        await self.adevice_control_write(dc)

    # synchronously requests that the DOT shouldn't power itself on when plugged into
    # a USB (e.g. when charging)
    def disable_power_on_by_usb_plug_in(self):
        asyncio.get_event_loop().run_until_complete(self.adisable_power_on_by_usb_plug_in())

    # asynchronously sets the output rate of the DOT
    #
    # (BLE spec sec. 2.2): only values 1,4,10,12,15,20,30,60,120hz are permitted
    async def aset_output_rate(self, rate):
        assert rate in {1, 4, 10, 12, 15, 20, 30, 60, 120}

        dc = await self.adevice_control_read()
        dc.visit_index = 0x10
        dc.output_rate = rate
        await self.adevice_control_write(dc)

    # synchronously sets the output rate of the DOT
    #
    # (BLE spec sec. 2.2): only values 1,4,10,12,15,20,30,60,120hz are permitted
    def set_output_rate(self, rate):
        asyncio.get_event_loop().run_until_complete(self.aset_output_rate(rate))

    # asynchronously resets the output rate of the DOT to its default value (60 hz)
    async def areset_output_rate(self):
        await self.aset_output_rate(60)  # default, according to BLE spec

    # synchronously resets the output rate of the DOT to its default value (60 hz)
    def reset_output_rate(self):
        asyncio.get_event_loop().run_until_complete(self.areset_output_rate())

    # asynchronously sets the "Filter Profile Index" field in the Device Control Characteristic
    #
    # this sets how the DOT filters measurements? No idea. See sec. 2.2 in the BLE
    # spec for a slightly better explanation
    async def aset_filter_profile_index(self, idx):
        assert idx in {0, 1}

        dc = await self.adevice_control_read()
        dc.visit_index = 0x20
        dc.filter_profile_index = idx
        await self.adevice_control_write(dc)

    # synchronously sets the "Filter Profile Index" field in the Device Control Characteristic
    #
    # this sets how the DOT filters measurements? No idea. See sec. 2.2 in the BLE
    # spec for a slightly better explanation
    def set_filter_profile_index(self, idx):
        asyncio.get_event_loop().run_until_complete(self.aset_filter_profile_index(idx))

    # asynchronously sets the "Filter Profile Index" of the DOT to "General"
    #
    # (from BLE spec sec. 2.2., table 8): "General" is the "Default for general human
    # motions"
    async def aset_filter_profile_to_general(self):
        await self.aset_filter_profile_index(0)

    # synchronously sets the "Filter Profile Index" of the DOT to "General"
    #
    # (from BLE spec sec. 2.2., table 8): "General" is the "Default for general human
    # motions"
    def set_filter_profile_to_general(self):
        asyncio.get_event_loop().run_until_complete(self.aset_filter_profile_to_general())

    # asynchronously sets the "Filter Profile Index" of the DOT to "Dynamic"
    #
    # (from BLE spec. sec. 2.2., table 8): "Dynamic" is "For fast and jerky human motions
    # like sprinting"
    async def aset_filter_profile_to_dynamic(self):
        await self.aset_filter_profile_index(1)

    # synchronously sets the "Filter Profile Index" of the DOT to "Dynamic"
    #
    # (from BLE spec. sec. 2.2., table 8): "Dynamic" is "For fast and jerky human motions
    # like sprinting"
    def set_filter_profile_to_dynamic(self):
        asyncio.get_event_loop().run_until_complete(self.aset_filter_profile_to_dynamic())

# a python `Callable` that is called whenever a notification is
# received by the bluetooth backend
class ResponseHandler:
    def __init__(self):
        self.i = 0

    def __call__(self, sender, data):
        self.i += 1

        parsed = MediumPayloadCompleteEuler.parse(data)
        print(f"i={self.i} t={parsed.timestamp.value} x={parsed.euler.x}, y={parsed.euler.y}, z={parsed.euler.z}")

# asynchronously returns `True` if the provided `bleak.backends.device.BLEDevice`
# is believed to be an XSens DOT sensor
async def ais_DOT(bledevice):
    if bledevice.name and "xsens dot" in bledevice.name:
        # spec: 1.2: Scanning and Filtering: tag name is "Xsens DOT"
        #
        # other devices in the wild *may* have a name collision with this, but it's
        # unlikely
        return True
    elif bledevice.metadata.get("manufacturer_data") and bledevice.metadata["manufacturer_data"].get(2182):
        # spec: 1.2: Scanning and Filtering: Bluetooth SIG identifier for XSens Technologies B.V. is 2182 (0x0886)
        #
        # this ambiguously identifies an XSens DOT. XSens might recycle its bluetooth
        # ID for other products, though, so we need to check that the device actually
        # responds to a DOT-like packet
        try:
            async with Dot(bledevice) as dot:
                await dot.adevice_info_read()  # typical request
                return True
        except asyncio.exceptions.TimeoutError as ex:
            return False

# synchronously returns `True` if the provided `bleak.backends.device.BLEDevice` is an
# XSens DOT
def is_DOT(bledevice):
    return asyncio.get_event_loop().run_until_complete(ais_DOT(bledevice))

# asynchronously returns a list of all (not just DOT) BLE devices that
# the host's bluetooth adaptor can see. Each element in the list is an
# instance of `bleak.backends.device.BLEDevice`
async def ascan_all():
    async with BleakScanner() as scanner:
        return list(await scanner.discover())

# synchronously returns a list of all (not just DOT) BLE devices that the
# host's bluetooth adaptor can see. Each element in the list is an instance
# of `bleak.backends.device.BLEDevice`
def scan_all():
    return asyncio.get_event_loop().run_until_complete(ascan_all_raw())

# asynchronously returns a list of all XSens DOTs that the host's bluetooth
# adaptor can see. Each element in the list is an instance of
# `bleak.backends.device.BLEDevice`
async def ascan():
    return [d for d in await ascan_all() if await ais_DOT(d)]

# synchronously returns a list of all XSens DOTs that the host's bluetooth
# adaptor can see. Each element in the list is an instance of
# `bleak.backends.device.BLEDevice`
def scan():
    return asyncio.get_event_loop().run_until_complete(ascan())

# asynchronously returns a BLE device with the given identifier/address
#
# returns `None` if the device cannot be found (e.g. no connection, wrong
# address)
async def afind_by_address(device_identifier):
    async with BleakScanner() as scanner:
        return await scanner.find_device_by_address(device_identifier)

# synchronously returns a BLE device with the given identifier/address
#
# returns `None` if the device cannot be found (e.g. no connection, wrong
# address)
def find_by_address(device_identifier):
    return asyncio.get_event_loop().run_until_complete(afind_by_address(device_identifier))

# asynchronously returns a BLE device with the given identifier/address if the
# device appears to be an XSens DOT
#
# effectively, the same as `afind_by_address` but with the extra stipulation that
# the given device must be a DOT
async def afind_dot_by_address(device_identifier):
    dev = await afind_by_address(device_identifier)

    if dev is None:
        return None  # device cannot be found
    elif not await ais_DOT(dev):
        return None  # device exists but is not a DOT
    else:
        return dev

# synchronously returns a BLE device with the given identifier/address, if the device
# appears to be an XSens DOT
#
# effectively, the same as `find_by_address`, but with the extra stipulation that
# the given device must be a DOT
def find_dot_by_address(device_identifier):
    return asyncio.get_event_loop().run_until_complete(afind_dot_by_address(device_identifier))


# low-level characteristic accessors (free functions)


# asynchronously returns the "Device Info Characteristic" for the given DOT device
#
# see: sec 2.1 Device Info Characteristic in DOT BLE spec
async def adevice_info_read(bledevice):
    async with Dot(bledevice) as dot:
        return await dot.adevice_info_read()

# synchronously returns the "Device Info Characteristic" for the given DOT device
#
# see: sec 2.1: Device Info Characteristic in DOT BLE spec
def device_info_read(bledevice):
    return asyncio.get_event_loop().run_until_complete(adevice_info_read(bledevice))

# asynchronously returns the "Device Control Characteristic" for the given DOT device
#
# see: sec 2.2: Device Control Characteristic in DOT BLE spec
async def adevice_control_read(bledevice):
    async with Dot(bledevice) as dot:
        return await dot.adevice_control_read()

# synchronously returns the "Device Control Characteristic" for the given DOT device
#
# see: sec 2.2: Device Control Characteristic in DOT BLE spec
def device_control_read(bledevice):
    return asyncio.get_event_loop().run_until_complete(adevice_control_read(bledevice))

# asynchronously write the provided DeviceControlCharacteristic to the provided
# DOT device
async def adevice_control_write(bledevice, device_control_characteristic):
    async with Dot(bledevice) as dot:
        await dot.adevice_control_write(device_control_characteristic)

def device_control_write(bledevice, device_control_characteristic):
    asyncio.get_event_loop().run_until_complete(adevice_control_write(bledevice, device_control_characteristic))

# high-level operations (free functions)

async def aidentify(bledevice):
    async with Dot(bledevice) as dot:
        await dot.aidentify()

def identify(bledevice):
    asyncio.get_event_loop().run_until_complete(aidentify(bledevice))

async def apower_off(bledevice):
    async with Dot(bledevice) as dot:
        await dot.apower_off()

def power_off(bledevice):
    asyncio.get_event_loop().run_until_complete(apower_off(bledevice))

async def aenable_power_on_by_usb_plug_in(bledevice):
    async with Dot(bledevice) as dot:
        await dot.aenable_power_on_by_usb_plug_in()

def enable_power_on_by_usb_plug_in(bledevice):
    asyncio.get_event_loop().run_until_complete(aenable_power_on_by_usb_plug_in(bledevice))

async def adisable_power_on_by_usb_plug_in(bledevice):
    async with Dot(bledevice) as dot:
        await dot.adisable_power_on_by_usb_plug_in()

def disable_power_on_by_usb_plug_in(bledevice):
    asyncio.get_event_loop().run_until_complete(adisable_power_on_by_usb_plug_in(bledevice))

async def aset_output_rate(bledevice, rate):
    async with Dot(bledevice) as dot:
        await dot.aset_output_rate(rate)

def set_output_rate(bledevice, rate):
    asyncio.get_event_loop().run_until_complete(aset_output_rate(bledevice, rate))

async def areset_output_rate(bledevice):
    async with Dot(bledevice) as dot:
        await dot.areset_output_rate()

def reset_output_rate(bledevice):
    asyncio.get_event_loop().run_until_complete(areset_output_rate(bledevice))

async def aset_filter_profile_index(bledevice, idx):
    async with Dot(bledevice) as dot:
        await dot.aset_filter_profile_index(idx)

def set_filter_profile_index(bledevice, idx):
    asyncio.get_event_loop().run_until_complete(aset_filter_profile_index(bledevice, idx))

def pump():
    asyncio.get_event_loop().run_forever()
