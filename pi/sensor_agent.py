"""
LISA Raspberry Pi Sensor Agent
Reads sensors, updates IoT Device Shadow, listens for lock commands.

Hardware: DHT22 (temp/humidity), MPU-6050 (G-force), GPS (gpsd), GPIO (lock relay)
"""

import json
import time
import math
import logging
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient

# ── Configuration ────────────────────────────────────────────────────────────
THING_NAME = "shipment-SHIP-001"   # must match DynamoDB shipmentId with "shipment-" prefix
ENDPOINT   = "XXXXXXXXXXXX.iot.us-east-1.amazonaws.com"   # from IoT Core → Settings
CERT_PATH  = "certs/device.pem.crt"
KEY_PATH   = "certs/private.pem.key"
CA_PATH    = "certs/root-CA.crt"
REPORT_INTERVAL_S = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Sensor reads ─────────────────────────────────────────────────────────────

def read_dht22():
    """Read temperature and humidity from DHT22 on GPIO pin 4."""
    try:
        import Adafruit_DHT
        humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, 4)
        if temperature is not None and humidity is not None:
            return round(temperature, 2), round(humidity, 1)
    except Exception as exc:
        log.warning(f"DHT22 read error: {exc}")
    return None, None


def read_mpu6050():
    """Read G-force magnitude from MPU-6050 via I2C."""
    try:
        import smbus2
        bus  = smbus2.SMBus(1)
        addr = 0x68
        bus.write_byte_data(addr, 0x6B, 0)   # wake up
        def read_word(reg):
            hi = bus.read_byte_data(addr, reg)
            lo = bus.read_byte_data(addr, reg + 1)
            val = (hi << 8) | lo
            return val - 65536 if val >= 32768 else val
        ax = read_word(0x3B) / 16384.0
        ay = read_word(0x3D) / 16384.0
        az = read_word(0x3F) / 16384.0
        return round(math.sqrt(ax**2 + ay**2 + az**2), 3)
    except Exception as exc:
        log.warning(f"MPU-6050 read error: {exc}")
    return None


def read_gps():
    """Read latitude and longitude from gpsd."""
    try:
        import gps
        session = gps.gps(mode=gps.WATCH_ENABLE | gps.WATCH_NEWSTYLE)
        for _ in range(10):
            report = session.next()
            if report['class'] == 'TPV' and hasattr(report, 'lat'):
                return round(report.lat, 6), round(report.lon, 6)
    except Exception as exc:
        log.warning(f"GPS read error: {exc}")
    return None, None


def read_battery():
    """Read battery level — implement for your ADC/fuel gauge chip."""
    return 87   # placeholder


def actuate_lock(lock_status):
    """Toggle GPIO relay for physical lock. HIGH = locked."""
    try:
        import RPi.GPIO as GPIO
        LOCK_PIN = 17
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(LOCK_PIN, GPIO.OUT)
        GPIO.output(LOCK_PIN, GPIO.HIGH if lock_status == "LOCKED" else GPIO.LOW)
        log.info(f"Lock actuated: {lock_status}")
    except Exception as exc:
        log.warning(f"GPIO lock error: {exc}")


# ── Shadow callbacks ─────────────────────────────────────────────────────────

_device_shadow = None

def on_shadow_delta(payload, response_status, token):
    """Called when dashboard sends a desired state change."""
    try:
        delta = json.loads(payload).get("state", {})
        log.info(f"Shadow delta received: {delta}")
        if "lockStatus" in delta:
            desired = delta["lockStatus"]
            actuate_lock(desired)
            # Confirm the new state back to shadow
            confirm = json.dumps({"state": {"reported": {"lockStatus": desired}}})
            _device_shadow.shadowUpdate(confirm, None, 5)
    except Exception as exc:
        log.error(f"Delta handler error: {exc}")


# ── Main loop ────────────────────────────────────────────────────────────────

def main():
    global _device_shadow

    client = AWSIoTMQTTShadowClient(THING_NAME)
    client.configureEndpoint(ENDPOINT, 8883)
    client.configureCredentials(CA_PATH, KEY_PATH, CERT_PATH)
    client.configureConnectDisconnectTimeout(10)
    client.configureMQTTOperationTimeout(5)
    client.connect()

    _device_shadow = client.createShadowHandlerWithName(THING_NAME, True)
    _device_shadow.shadowRegisterDeltaCallback(on_shadow_delta)
    log.info(f"Connected as {THING_NAME}")

    while True:
        temperature, humidity = read_dht22()
        g_force               = read_mpu6050()
        latitude, longitude   = read_gps()
        battery               = read_battery()

        reported = {"online": True}
        if temperature  is not None: reported["temperature"]  = temperature
        if humidity     is not None: reported["humidity"]     = humidity
        if g_force      is not None: reported["gForce"]       = g_force
        if latitude     is not None: reported["latitude"]     = latitude
        if longitude    is not None: reported["longitude"]    = longitude
        if battery      is not None: reported["batteryLevel"] = battery

        payload = json.dumps({"state": {"reported": reported}})
        _device_shadow.shadowUpdate(payload, None, 5)
        log.info(f"Shadow updated: {reported}")

        time.sleep(REPORT_INTERVAL_S)


if __name__ == "__main__":
    main()
