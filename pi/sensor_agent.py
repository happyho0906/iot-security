"""Raspberry Pi sensor agent — reads DHT22/MPU-6050/GPS, updates IoT Device Shadow."""

import json
import time
import math
import logging
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient

# Configuration — update per device
THING_NAME        = "shipment-SHIP-001"
ENDPOINT          = "XXXXXXXXXXXX.iot.us-east-1.amazonaws.com"
CERT_PATH         = "certs/device.pem.crt"
KEY_PATH          = "certs/private.pem.key"
CA_PATH           = "certs/root-CA.crt"
REPORT_INTERVAL_S = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def read_dht22():
    """DHT22 on GPIO pin 4 — returns (temperature_C, humidity_pct)."""
    try:
        import Adafruit_DHT
        humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, 4)
        if temperature is not None and humidity is not None:
            return round(temperature, 2), round(humidity, 1)
    except Exception as exc:
        log.warning(f"DHT22: {exc}")
    return None, None


def read_mpu6050():
    """MPU-6050 via I2C — returns G-force magnitude."""
    try:
        import smbus2
        bus  = smbus2.SMBus(1)
        addr = 0x68
        bus.write_byte_data(addr, 0x6B, 0)
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
        log.warning(f"MPU-6050: {exc}")
    return None


def read_gps():
    """gpsd — returns (latitude, longitude)."""
    try:
        import gps
        session = gps.gps(mode=gps.WATCH_ENABLE | gps.WATCH_NEWSTYLE)
        for _ in range(10):
            report = session.next()
            if report['class'] == 'TPV' and hasattr(report, 'lat'):
                return round(report.lat, 6), round(report.lon, 6)
    except Exception as exc:
        log.warning(f"GPS: {exc}")
    return None, None


def read_battery():
    """Battery percent — replace with ADC/fuel gauge read."""
    return 87


def actuate_lock(lock_status):
    """GPIO relay on pin 17 — HIGH = locked."""
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(17, GPIO.OUT)
        GPIO.output(17, GPIO.HIGH if lock_status == "LOCKED" else GPIO.LOW)
        log.info(f"Lock: {lock_status}")
    except Exception as exc:
        log.warning(f"GPIO: {exc}")


_device_shadow = None


def on_shadow_delta(payload, response_status, token):
    try:
        delta = json.loads(payload).get("state", {})
        if "lockStatus" in delta:
            desired = delta["lockStatus"]
            actuate_lock(desired)
            confirm = json.dumps({"state": {"reported": {"lockStatus": desired}}})
            _device_shadow.shadowUpdate(confirm, None, 5)
    except Exception as exc:
        log.error(f"Delta: {exc}")


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
    log.info(f"Connected: {THING_NAME}")

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
