#!/usr/bin/env python3
"""
Sensor Debugging Script for Raspberry Pi
This script will help diagnose issues with your sensor connections
"""

import time
import sys
from datetime import datetime

# Check if we're on Raspberry Pi
try:
    import RPi.GPIO as GPIO
    import Adafruit_DHT
    SIMULATION_MODE = False
    print("✓ Successfully imported RPi.GPIO and Adafruit_DHT")
except ImportError as e:
    print(f"✗ Import Error: {e}")
    print("Please install required packages:")
    print("sudo apt update")
    print("sudo apt install python3-pip")
    print("pip3 install RPi.GPIO")
    print("pip3 install Adafruit_DHT")
    sys.exit(1)

# Pin definitions (matching your code)
ULTRASONIC_TRIGGER = 18
ULTRASONIC_ECHO = 24
MQ135_DIGITAL = 25
MQ135_ANALOG = 26
DHT11_DATA = 22
LDR_PIN = 21
PIR_DATA = 23

def setup_gpio():
    """Setup GPIO with proper error handling"""
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        print("✓ GPIO setup successful")
        return True
    except Exception as e:
        print(f"✗ GPIO setup failed: {e}")
        return False

def test_ultrasonic():
    """Test HC-SR04 Ultrasonic Sensor"""
    print("\n=== Testing HC-SR04 Ultrasonic Sensor ===")
    print(f"Trigger Pin: {ULTRASONIC_TRIGGER}, Echo Pin: {ULTRASONIC_ECHO}")
    
    try:
        # Setup pins
        GPIO.setup(ULTRASONIC_TRIGGER, GPIO.OUT)
        GPIO.setup(ULTRASONIC_ECHO, GPIO.IN)
        
        # Initial state
        GPIO.output(ULTRASONIC_TRIGGER, False)
        time.sleep(0.1)
        
        # Send trigger pulse
        GPIO.output(ULTRASONIC_TRIGGER, True)
        time.sleep(0.00001)  # 10 microseconds
        GPIO.output(ULTRASONIC_TRIGGER, False)
        
        # Wait for echo
        timeout = time.time() + 0.5  # 500ms timeout
        while GPIO.input(ULTRASONIC_ECHO) == 0:
            pulse_start = time.time()
            if time.time() > timeout:
                print("✗ Timeout waiting for echo start")
                return False
        
        while GPIO.input(ULTRASONIC_ECHO) == 1:
            pulse_end = time.time()
            if time.time() > timeout:
                print("✗ Timeout waiting for echo end")
                return False
        
        # Calculate distance
        pulse_duration = pulse_end - pulse_start
        distance = (pulse_duration * 34300) / 2
        
        if 2 <= distance <= 400:
            print(f"✓ Distance: {distance:.2f} cm")
            return True
        else:
            print(f"✗ Distance out of range: {distance:.2f} cm")
            return False
            
    except Exception as e:
        print(f"✗ Ultrasonic test failed: {e}")
        return False

def test_dht11():
    """Test DHT11 Temperature and Humidity Sensor"""
    print("\n=== Testing DHT11 Sensor ===")
    print(f"Data Pin: {DHT11_DATA}")
    
    try:
        # Try multiple times as DHT11 can be unreliable
        for attempt in range(3):
            print(f"Attempt {attempt + 1}/3...")
            humidity, temperature = Adafruit_DHT.read_retry(
                Adafruit_DHT.DHT11, 
                DHT11_DATA, 
                retries=5, 
                delay_seconds=2
            )
            
            if humidity is not None and temperature is not None:
                print(f"✓ Temperature: {temperature:.1f}°C")
                print(f"✓ Humidity: {humidity:.1f}%")
                return True
            else:
                print(f"✗ Attempt {attempt + 1} failed")
                time.sleep(2)
        
        print("✗ DHT11 test failed after 3 attempts")
        print("Check wiring: VCC->3.3V, GND->GND, DATA->GPIO22")
        return False
        
    except Exception as e:
        print(f"✗ DHT11 test failed: {e}")
        return False

def test_pir():
    """Test PIR Motion Sensor"""
    print("\n=== Testing PIR Motion Sensor ===")
    print(f"Data Pin: {PIR_DATA}")
    
    try:
        GPIO.setup(PIR_DATA, GPIO.IN)
        
        print("PIR sensor warming up (5 seconds)...")
        time.sleep(5)
        
        print("Reading PIR for 10 seconds (try moving in front of sensor)...")
        motion_detected = False
        
        for i in range(10):
            if GPIO.input(PIR_DATA):
                print(f"✓ Motion detected at second {i + 1}")
                motion_detected = True
            else:
                print(f"- No motion at second {i + 1}")
            time.sleep(1)
        
        if motion_detected:
            print("✓ PIR sensor is working")
            return True
        else:
            print("⚠ No motion detected - try moving in front of sensor")
            return False
            
    except Exception as e:
        print(f"✗ PIR test failed: {e}")
        return False

def test_ldr():
    """Test LDR Light Sensor"""
    print("\n=== Testing LDR Light Sensor ===")
    print(f"LDR Pin: {LDR_PIN}")
    
    try:
        def rc_time():
            count = 0
            # Discharge capacitor
            GPIO.setup(LDR_PIN, GPIO.OUT)
            GPIO.output(LDR_PIN, GPIO.LOW)
            time.sleep(0.1)
            
            # Count time to charge
            GPIO.setup(LDR_PIN, GPIO.IN)
            start_time = time.time()
            
            while GPIO.input(LDR_PIN) == GPIO.LOW:
                count += 1
                if count > 1000000 or (time.time() - start_time) > 2:
                    break
            
            return count
        
        # Take multiple readings
        readings = []
        for i in range(3):
            reading = rc_time()
            readings.append(reading)
            print(f"Reading {i + 1}: {reading}")
            time.sleep(0.5)
        
        avg_reading = sum(readings) / len(readings)
        print(f"✓ Average LDR reading: {avg_reading:.0f}")
        print("Try covering/uncovering the LDR to see changes")
        return True
        
    except Exception as e:
        print(f"✗ LDR test failed: {e}")
        return False

def test_mq135():
    """Test MQ-135 Air Quality Sensor"""
    print("\n=== Testing MQ-135 Air Quality Sensor ===")
    print(f"Digital Pin: {MQ135_DIGITAL}, Analog Pin: {MQ135_ANALOG}")
    
    try:
        # Test digital pin
        GPIO.setup(MQ135_DIGITAL, GPIO.IN)
        digital_value = GPIO.input(MQ135_DIGITAL)
        print(f"Digital reading: {digital_value} ({'Gas detected' if not digital_value else 'No gas'})")
        
        # Test analog using RC method
        def read_analog():
            count = 0
            GPIO.setup(MQ135_ANALOG, GPIO.OUT)
            GPIO.output(MQ135_ANALOG, GPIO.LOW)
            time.sleep(0.01)
            
            GPIO.setup(MQ135_ANALOG, GPIO.IN)
            start_time = time.time()
            
            while GPIO.input(MQ135_ANALOG) == GPIO.LOW:
                count += 1
                if count > 100000 or (time.time() - start_time) > 1:
                    break
            
            return count
        
        analog_reading = read_analog()
        print(f"✓ Analog reading: {analog_reading}")
        print("Note: MQ-135 needs warm-up time (24-48 hours for accurate readings)")
        return True
        
    except Exception as e:
        print(f"✗ MQ-135 test failed: {e}")
        return False

def check_pin_conflicts():
    """Check for pin conflicts and system issues"""
    print("\n=== Checking System Status ===")
    
    # Check if SPI/I2C might be interfering
    try:
        with open('/boot/config.txt', 'r') as f:
            config = f.read()
            if 'dtparam=spi=on' in config:
                print("⚠ SPI is enabled - might conflict with some GPIO pins")
            if 'dtparam=i2c_arm=on' in config:
                print("⚠ I2C is enabled - might conflict with some GPIO pins")
    except:
        pass
    
    # Check GPIO pin status
    print("\nGPIO Pin Usage:")
    pins_to_check = [ULTRASONIC_TRIGGER, ULTRASONIC_ECHO, MQ135_DIGITAL, 
                     MQ135_ANALOG, DHT11_DATA, LDR_PIN, PIR_DATA]
    
    for pin in pins_to_check:
        try:
            GPIO.setup(pin, GPIO.IN)
            print(f"GPIO {pin}: Available")
        except Exception as e:
            print(f"GPIO {pin}: Error - {e}")

def main():
    """Main debugging function"""
    print("=== Raspberry Pi Sensor Debugging Script ===")
    print("This script will test each sensor individually")
    print("Make sure all sensors are connected properly before running")
    print("")
    
    if not setup_gpio():
        return
    
    # Test each sensor
    results = {}
    
    try:
        # Run tests
        results['ultrasonic'] = test_ultrasonic()
        results['dht11'] = test_dht11()
        results['pir'] = test_pir()
        results['ldr'] = test_ldr()
        results['mq135'] = test_mq135()
        
        # System checks
        check_pin_conflicts()
        
        # Summary
        print("\n" + "="*50)
        print("SUMMARY")
        print("="*50)
        
        for sensor, status in results.items():
            status_str = "✓ PASS" if status else "✗ FAIL"
            print(f"{sensor.upper():12}: {status_str}")
        
        passed = sum(results.values())
        total = len(results)
        print(f"\nPassed: {passed}/{total} sensors")
        
        if passed == 0:
            print("\n❌ No sensors working - Check:")
            print("1. Power connections (3.3V/5V and GND)")
            print("2. GPIO pin connections")
            print("3. Sensor compatibility")
            print("4. Wiring integrity")
        elif passed < total:
            print(f"\n⚠ Some sensors failed - Check failed sensors")
        else:
            print(f"\n✅ All sensors working!")
            
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
    finally:
        GPIO.cleanup()
        print("GPIO cleanup completed")

if __name__ == "__main__":
    main()