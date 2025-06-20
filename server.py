#!/usr/bin/env python3
"""
Multi-Sensor API Server for Raspberry Pi
Supports Ultrasonic (HC-SR04), MQ-135 Air Quality, DHT11 Temperature/Humidity,
LDR Light Sensor, and PIR Motion Sensor
Direct GPIO connections without MCP3008
Exposes sensor data via FastAPI REST API
"""

import time
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from threading import Thread, Lock
import logging
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

# Uncomment these imports when running on Raspberry Pi
try:
    import RPi.GPIO as GPIO
    import Adafruit_DHT
    SIMULATION_MODE = False
    print("Real hardware mode enabled")
except ImportError:
    SIMULATION_MODE = True
    print("WARNING: Running in simulation mode - install RPi.GPIO and Adafruit_DHT")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data Models
class SensorReading(BaseModel):
    AlertType: str
    assetId: str
    Description: str
    Date: str
    Report: str
    App: str
    anchor: str
    Stage_x007b__x0023__x007d_: str
    Failure_x0020_Class: str
    id: str
    Priority: str
    OperatorNumber: str
    OperatorName: str
    ManagerName: str
    ManagerNumber: str
    GoogleDriveURL: str

class ApiResponse(BaseModel):
    data: List[Dict]
    shouldSubscribe: str

class BaseSensor:
    def __init__(self, sensor_id: str, asset_id: str):
        self.sensor_id = sensor_id
        self.asset_id = asset_id
        self.last_reading_time = None
        self.lock = Lock()
        self.alerts = []
        
    def generate_alert(self, alert_type: str, description: str, failure_class: str = "NaN") -> Dict:
        alert_id = f"{self.sensor_id}_{int(time.time())}"
        return {
            "AlertType": alert_type,
            "assetId": "MCN-02",
            "Description": description,
            "Date": datetime.now(timezone.utc).isoformat(),
            "Report": "NaN",
            "App": "IoT Sensor System",
            "anchor": self.asset_id,
            "Stage_x007b__x0023__x007d_": "NaN",
            "Failure_x0020_Class": failure_class,
            "id": alert_id,
            "Priority": "NaN",
            "OperatorNumber": "NaN",
            "OperatorName": "NaN",
            "ManagerName": "NaN",
            "ManagerNumber": "NaN",
            "GoogleDriveURL": "NaN"
        }

class UltrasonicSensor(BaseSensor):
    def __init__(self, sensor_id: str = "ULTRASONIC-01", asset_id: str = "DIST-SENSOR-01", 
                 trigger_pin: int = 18, echo_pin: int = 24):
        super().__init__(sensor_id, asset_id)
        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin
        self.distance = 0.0
        self.min_distance_threshold = 10.0  # cm
        self.max_distance_threshold = 200.0  # cm
        
        # Initialize GPIO pins
        self.setup_pins()
        
    def setup_pins(self):
        """Setup GPIO pins for ultrasonic sensor"""
        if not SIMULATION_MODE:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.trigger_pin, GPIO.OUT)
                GPIO.setup(self.echo_pin, GPIO.IN)
                GPIO.output(self.trigger_pin, False)
                time.sleep(0.1)  # Let sensor settle
            except Exception as e:
                logger.error(f"Error setting up ultrasonic pins: {e}")
        
    def measure_distance(self) -> Optional[float]:
        """Measure distance using ultrasonic sensor (HC-SR04)"""
        if SIMULATION_MODE:
            return None  # Return None instead of random values
            
        try:
            # Ensure pins are set correctly
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.trigger_pin, GPIO.OUT)
            GPIO.setup(self.echo_pin, GPIO.IN)
            
            # Clear trigger
            GPIO.output(self.trigger_pin, False)
            time.sleep(0.000002)  # 2 microseconds
            
            # Send 10us pulse to trigger
            GPIO.output(self.trigger_pin, True)
            time.sleep(0.00001)  # 10 microseconds
            GPIO.output(self.trigger_pin, False)
            
            # Wait for echo to start
            timeout_start = time.time()
            while GPIO.input(self.echo_pin) == 0:
                pulse_start = time.time()
                if pulse_start - timeout_start > 0.1:  # 100ms timeout
                    logger.warning("Ultrasonic timeout waiting for echo start")
                    return None
            
            # Wait for echo to stop
            timeout_end = time.time()
            while GPIO.input(self.echo_pin) == 1:
                pulse_end = time.time()
                if pulse_end - timeout_end > 0.1:  # 100ms timeout
                    logger.warning("Ultrasonic timeout waiting for echo end")
                    return None
            
            # Calculate distance
            pulse_duration = pulse_end - pulse_start
            distance = (pulse_duration * 34300) / 2
            
            # Validate HC-SR04 range (2cm to 400cm)
            if 2 <= distance <= 400:
                return round(distance, 2)
            else:
                logger.warning(f"Distance out of range: {distance}cm")
                return None
                
        except Exception as e:
            logger.error(f"Ultrasonic sensor error: {e}")
            return None

            
    def update_reading(self):
        """Update the current distance reading and check for alerts"""
        distance = self.measure_distance()
        if distance is not None:
            with self.lock:
                self.distance = distance
                self.last_reading_time = datetime.now(timezone.utc)
                
                if distance < self.min_distance_threshold:
                    alert = self.generate_alert(
                        "Proximity Alert",
                        f"Object detected within {self.min_distance_threshold}cm. Current distance: {distance}cm",
                        "Proximity_Warning"
                    )
                    self.alerts.append(alert)
                elif distance > self.max_distance_threshold:
                    alert = self.generate_alert(
                        "Range Alert",
                        f"No object detected within range. Current distance: {distance}cm",
                        "Range_Warning"
                    )
                    self.alerts.append(alert)
                    
    def get_reading(self) -> Dict:
        """Get the current distance reading"""
        with self.lock:
            return {
                'sensor_type': 'ultrasonic',
                'sensor_id': self.sensor_id,
                'distance_cm': self.distance,
                'distance_inches': round(self.distance / 2.54, 2),
                'timestamp': self.last_reading_time.isoformat() if self.last_reading_time else None,
                'status': 'active' if self.last_reading_time else 'no_reading',
                'pins': {'trigger': self.trigger_pin, 'echo': self.echo_pin}
            }

class MQ135Sensor(BaseSensor):
    def __init__(self, sensor_id: str = "MQ135-01", asset_id: str = "AIR-QUALITY-01", 
                 digital_pin: int = 25, analog_pin: int = 26):
        super().__init__(sensor_id, asset_id)
        self.digital_pin = digital_pin  # Digital output pin
        self.analog_pin = analog_pin    # Using capacitor discharge method for analog
        self.air_quality_ppm = 0.0
        self.gas_detected = False
        self.danger_threshold = 1000  # ppm
        self.warning_threshold = 500  # ppm
        
        self.setup_pins()
        
    def setup_pins(self):
        """Setup GPIO pins for MQ-135 sensor"""
        if not SIMULATION_MODE:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.digital_pin, GPIO.IN)
                # analog_pin will be configured dynamically in read_analog_value
            except Exception as e:
                logger.error(f"Error setting up MQ-135 pins: {e}")
        
    def read_air_quality(self) -> Optional[tuple]:
        """Read air quality from MQ-135 sensor"""
        if SIMULATION_MODE:
            return None, None  # Return None instead of random values
            
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.digital_pin, GPIO.IN)
            
            # Read digital pin
            gas_detected = not GPIO.input(self.digital_pin)  # Usually LOW when gas detected
            
            # Read analog using RC circuit method
            def read_analog():
                count = 0
                GPIO.setup(self.analog_pin, GPIO.OUT)
                GPIO.output(self.analog_pin, GPIO.LOW)
                time.sleep(0.01)  # Discharge
                
                GPIO.setup(self.analog_pin, GPIO.IN)
                start_time = time.time()
                
                while GPIO.input(self.analog_pin) == GPIO.LOW:
                    count += 1
                    if count > 100000 or (time.time() - start_time) > 1:
                        break
                
                return count
            
            analog_reading = read_analog()
            
            # Convert to PPM (this needs calibration for your specific sensor)
            # Basic conversion - you may need to adjust based on your sensor's datasheet
            if analog_reading > 0:
                ppm = (analog_reading / 10000) * 1000  # Simplified conversion
                ppm = min(ppm, 2000)  # Cap at reasonable max
            else:
                ppm = 0
            
            return gas_detected, round(ppm, 2)

        except Exception as e:
            logger.error(f"MQ135 sensor error: {e}")
            return None, None


    def update_reading(self):
        """Update air quality reading and check for alerts"""
        result = self.read_air_quality()
        if result is not None:
            gas_detected, ppm = result
            if gas_detected is not None and ppm is not None:
                with self.lock:
                    self.gas_detected = gas_detected
                    self.air_quality_ppm = ppm
                    self.last_reading_time = datetime.now(timezone.utc)
                    
                    if ppm > self.danger_threshold:
                        alert = self.generate_alert(
                            "Air Quality Critical",
                            f"Dangerous air quality detected: {ppm} PPM. Immediate action required.",
                            "Air_Quality_Critical"
                        )
                        self.alerts.append(alert)
                    elif ppm > self.warning_threshold:
                        alert = self.generate_alert(
                            "Air Quality Warning",
                            f"Poor air quality detected: {ppm} PPM. Monitor closely.",
                            "Air_Quality_Warning"
                        )
                        self.alerts.append(alert)
                    
    def get_reading(self) -> Dict:
        """Get current air quality reading"""
        with self.lock:
            quality_level = "Good"
            if self.air_quality_ppm > self.danger_threshold:
                quality_level = "Dangerous"
            elif self.air_quality_ppm > self.warning_threshold:
                quality_level = "Poor"
                
            return {
                'sensor_type': 'air_quality',
                'sensor_id': self.sensor_id,
                'air_quality_ppm': self.air_quality_ppm,
                'gas_detected': self.gas_detected,
                'quality_level': quality_level,
                'timestamp': self.last_reading_time.isoformat() if self.last_reading_time else None,
                'status': 'active' if self.last_reading_time else 'no_reading',
                'pins': {'digital': self.digital_pin, 'analog': self.analog_pin}
            }

class DHT11Sensor(BaseSensor):
    def __init__(self, sensor_id: str = "DHT11-01", asset_id: str = "TEMP-HUM-01", 
                 data_pin: int = 22):
        super().__init__(sensor_id, asset_id)
        self.data_pin = data_pin
        self.temperature = 0.0
        self.humidity = 0.0
        self.temp_high_threshold = 35.0  # Celsius
        self.temp_low_threshold = 5.0    # Celsius
        self.humidity_high_threshold = 80.0  # %
        self.humidity_low_threshold = 20.0   # %
        
    def read_temp_humidity(self) -> tuple:
        """Read temperature and humidity from DHT11"""
        if SIMULATION_MODE:
            return None, None  # Return None instead of random values
            
        try:
            # Use proper DHT11 reading with retries
            humidity, temperature = Adafruit_DHT.read_retry(
                Adafruit_DHT.DHT11, 
                self.data_pin, 
                retries=5, 
                delay_seconds=1
            )
            
            if humidity is not None and temperature is not None:
                # Validate DHT11 ranges
                if 20 <= humidity <= 95 and 0 <= temperature <= 60:
                    return round(humidity, 1), round(temperature, 1)
                else:
                    logger.warning(f"DHT11 values out of range: H={humidity}%, T={temperature}°C")
                    return None, None
            else:
                logger.warning("DHT11 returned None values")
                return None, None
                
        except Exception as e:
            logger.error(f"DHT11 sensor error: {e}")
            return None, None


    def update_reading(self):
        """Update temperature and humidity readings and check for alerts"""
        humidity, temperature = self.read_temp_humidity()
        if humidity is not None and temperature is not None:
            with self.lock:
                self.humidity = round(humidity, 2)
                self.temperature = round(temperature, 2)
                self.last_reading_time = datetime.now(timezone.utc)
                
                if temperature > self.temp_high_threshold:
                    alert = self.generate_alert(
                        "Temperature Alert",
                        f"High temperature detected: {temperature}°C",
                        "Temperature_High"
                    )
                    self.alerts.append(alert)
                elif temperature < self.temp_low_threshold:
                    alert = self.generate_alert(
                        "Temperature Alert",
                        f"Low temperature detected: {temperature}°C",
                        "Temperature_Low"
                    )
                    self.alerts.append(alert)
                    
                if humidity > self.humidity_high_threshold:
                    alert = self.generate_alert(
                        "Humidity Alert",
                        f"High humidity detected: {humidity}%",
                        "Humidity_High"
                    )
                    self.alerts.append(alert)
                elif humidity < self.humidity_low_threshold:
                    alert = self.generate_alert(
                        "Humidity Alert",
                        f"Low humidity detected: {humidity}%",
                        "Humidity_Low"
                    )
                    self.alerts.append(alert)
                    
    def get_reading(self) -> Dict:
        """Get current temperature and humidity reading"""
        with self.lock:
            return {
                'sensor_type': 'temperature_humidity',
                'sensor_id': self.sensor_id,
                'temperature_celsius': self.temperature,
                'temperature_fahrenheit': round((self.temperature * 9/5) + 32, 2),
                'humidity_percent': self.humidity,
                'timestamp': self.last_reading_time.isoformat() if self.last_reading_time else None,
                'status': 'active' if self.last_reading_time else 'no_reading',
                'pins': {'data': self.data_pin}
            }

class LDRSensor(BaseSensor):
    def __init__(self, sensor_id: str = "LDR-01", asset_id: str = "LIGHT-SENSOR-01", 
                 ldr_pin: int = 21):
        super().__init__(sensor_id, asset_id)
        self.ldr_pin = ldr_pin
        self.light_level = 0
        self.light_percentage = 0.0
        self.dark_threshold = 20.0  # Below 20% is considered dark
        self.bright_threshold = 80.0  # Above 80% is considered very bright
        
        self.setup_pins()
        
    def setup_pins(self):
        """Setup GPIO pins for LDR sensor"""
        if not SIMULATION_MODE:
            try:
                GPIO.setmode(GPIO.BCM)
                # Pin will be configured dynamically in rc_time
            except Exception as e:
                logger.error(f"Error setting up LDR pins: {e}")
        
    def read_light_level(self) -> Optional[tuple]:
        """Read light level from LDR sensor"""
        if SIMULATION_MODE:
            return None, None  # Return None instead of random values
            
        try:
            GPIO.setmode(GPIO.BCM)
            
            def rc_time():
                count = 0
                # Discharge capacitor
                GPIO.setup(self.ldr_pin, GPIO.OUT)
                GPIO.output(self.ldr_pin, GPIO.LOW)
                time.sleep(0.1)
                
                # Count time to charge
                GPIO.setup(self.ldr_pin, GPIO.IN)
                start_time = time.time()
                
                while GPIO.input(self.ldr_pin) == GPIO.LOW:
                    count += 1
                    if count > 1000000 or (time.time() - start_time) > 2:
                        break
                
                return count
            
            raw_reading = rc_time()
            
            if raw_reading > 0:
                # Convert to percentage (adjust these values based on your setup)
                max_dark = 1000000  # Very dark reading
                min_bright = 1000   # Very bright reading
                
                if raw_reading >= max_dark:
                    percentage = 0  # Very dark
                elif raw_reading <= min_bright:
                    percentage = 100  # Very bright
                else:
                    # Linear interpolation
                    percentage = 100 * (1 - ((raw_reading - min_bright) / (max_dark - min_bright)))
                    percentage = max(0, min(100, percentage))
                
                return raw_reading, round(percentage, 2)
            else:
                return None, None
                
        except Exception as e:
            logger.error(f"LDR sensor error: {e}")
            return None, None


    def update_reading(self):
        """Update light level reading and check for alerts"""
        result = self.read_light_level()
        if result is not None:
            raw_value, percentage = result
            if raw_value is not None and percentage is not None:
                with self.lock:
                    self.light_level = raw_value
                    self.light_percentage = percentage
                    self.last_reading_time = datetime.now(timezone.utc)
                    
                    if percentage < self.dark_threshold:
                        alert = self.generate_alert(
                            "Light Level Alert",
                            f"Dark environment detected: {percentage}% light level",
                            "Light_Dark"
                        )
                        self.alerts.append(alert)
                    elif percentage > self.bright_threshold:
                        alert = self.generate_alert(
                            "Light Level Alert",
                            f"Very bright environment detected: {percentage}% light level",
                            "Light_Bright"
                        )
                        self.alerts.append(alert)
                    
    def get_reading(self) -> Dict:
        """Get current light level reading"""
        with self.lock:
            light_condition = "Normal"
            if self.light_percentage < self.dark_threshold:
                light_condition = "Dark"
            elif self.light_percentage > self.bright_threshold:
                light_condition = "Very Bright"
                
            return {
                'sensor_type': 'light_sensor',
                'sensor_id': self.sensor_id,
                'light_level_raw': self.light_level,
                'light_percentage': self.light_percentage,
                'light_condition': light_condition,
                'timestamp': self.last_reading_time.isoformat() if self.last_reading_time else None,
                'status': 'active' if self.last_reading_time else 'no_reading',
                'pins': {'ldr': self.ldr_pin}
            }

class PIRSensor(BaseSensor):
    def __init__(self, sensor_id: str = "PIR-01", asset_id: str = "MOTION-SENSOR-01", 
                 data_pin: int = 23):
        super().__init__(sensor_id, asset_id)
        self.data_pin = data_pin
        self.motion_detected = False
        self.motion_count = 0
        self.last_motion_time = None
        self.motion_timeout = 30  # seconds - alert if no motion for this long
        
        self.setup_pins()
        
    def setup_pins(self):
        """Setup GPIO pins for PIR sensor"""
        if not SIMULATION_MODE:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.data_pin, GPIO.IN)
                time.sleep(2)  # PIR sensor warm-up time
            except Exception as e:
                logger.error(f"Error setting up PIR pins: {e}")
        
    def read_motion(self) -> Optional[bool]:
        """Read motion detection from PIR sensor"""
        if SIMULATION_MODE:
            return None  # Return None instead of random values
            
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.data_pin, GPIO.IN)
            
            # PIR output is HIGH when motion detected
            motion = GPIO.input(self.data_pin)
            return bool(motion)
            
        except Exception as e:
            logger.error(f"PIR sensor error: {e}")
            return None

            
    def update_reading(self):
        """Update motion detection and check for alerts"""
        motion = self.read_motion()
        current_time = datetime.now(timezone.utc)
        
        with self.lock:
            self.last_reading_time = current_time
            
            if motion:
                if not self.motion_detected:  # Motion just started
                    self.motion_count += 1
                    alert = self.generate_alert(
                        "Motion Detected",
                        f"Motion detected by sensor. Total detections: {self.motion_count}",
                        "Motion_Detected"
                    )
                    self.alerts.append(alert)
                
                self.motion_detected = True
                self.last_motion_time = current_time
            else:
                self.motion_detected = False
                
                # Check for no motion timeout
                if (self.last_motion_time and 
                    (current_time - self.last_motion_time).total_seconds() > self.motion_timeout):
                    alert = self.generate_alert(
                        "No Motion Alert",
                        f"No motion detected for over {self.motion_timeout} seconds",
                        "Motion_Timeout"
                    )
                    self.alerts.append(alert)
                    
    def get_reading(self) -> Dict:
        """Get current motion detection status"""
        with self.lock:
            time_since_motion = None
            if self.last_motion_time:
                time_since_motion = (datetime.now(timezone.utc) - self.last_motion_time).total_seconds()
                
            return {
                'sensor_type': 'motion_sensor',
                'sensor_id': self.sensor_id,
                'motion_detected': self.motion_detected,
                'motion_count': self.motion_count,
                'last_motion_time': self.last_motion_time.isoformat() if self.last_motion_time else None,
                'time_since_motion_seconds': round(time_since_motion, 2) if time_since_motion else None,
                'timestamp': self.last_reading_time.isoformat() if self.last_reading_time else None,
                'status': 'active' if self.last_reading_time else 'no_reading',
                'pins': {'data': self.data_pin}
            }

# Initialize sensors with direct GPIO pins
ultrasonic_sensor = UltrasonicSensor(trigger_pin=18, echo_pin=24)
mq135_sensor = MQ135Sensor(digital_pin=25, analog_pin=26)
dht11_sensor = DHT11Sensor(data_pin=22)
ldr_sensor = LDRSensor(ldr_pin=21)
pir_sensor = PIRSensor(data_pin=23)

sensors = {
    'ultrasonic': ultrasonic_sensor,
    'mq135': mq135_sensor,
    'dht11': dht11_sensor,
    'ldr': ldr_sensor,
    'pir': pir_sensor
}

app = FastAPI(
    title="Multi-Sensor IoT API - Direct GPIO",
    description="REST API for Ultrasonic, MQ-135, DHT11, LDR, and PIR sensors on Raspberry Pi with direct GPIO connections",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

origins = ["*"]  # This allows all origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allows all headers
)

# Middleware to add ngrok bypass headers
@app.middleware("http")
async def add_ngrok_bypass_headers(request: Request, call_next):
    response = await call_next(request)
    
    # Add ngrok bypass headers to all responses
    response.headers["ngrok-skip-browser-warning"] = "true"
    response.headers["User-Agent"] = "CustomSensorAPI/1.0"
    
    return response

@app.get("/sensors", response_class=PlainTextResponse)
async def get_all_sensors(request: Request):
    try:
        readings = []
        for sensor_type, sensor in sensors.items():
            readings.append(sensor.get_reading())
        response = ApiResponse(data=readings, shouldSubscribe="true")
        
        # Create response with ngrok bypass headers
        content = json.dumps(response.dict(), indent=2)
        headers = {
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "CustomSensorAPI/1.0"
        }
        return PlainTextResponse(content=content, headers=headers)
    except Exception as e:
        logger.error(f"Error getting all sensors: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/sensors/alerts", response_class=PlainTextResponse)
async def get_sensor_alerts(request: Request):
    try:
        all_alerts = []
        for sensor in sensors.values():
            with sensor.lock:
                all_alerts.extend(sensor.alerts[-10:])
        all_alerts.sort(key=lambda x: x['Date'], reverse=True)
        response = ApiResponse(data=all_alerts, shouldSubscribe="true")
        
        # Create response with ngrok bypass headers
        content = json.dumps(response.dict(), indent=2)
        headers = {
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "CustomSensorAPI/1.0"
        }
        return PlainTextResponse(content=content, headers=headers)
    except Exception as e:
        logger.error(f"Error getting sensor alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/sensors/{sensor_type}", response_class=PlainTextResponse)
async def get_sensor(sensor_type: str, request: Request):
    if sensor_type not in sensors:
        raise HTTPException(status_code=404, detail=f"Sensor type '{sensor_type}' not found. Available: {list(sensors.keys())}")
    try:
        reading = [sensors[sensor_type].get_reading()]
        response = ApiResponse(data=reading, shouldSubscribe="true")
        
        # Create response with ngrok bypass headers
        content = json.dumps(response.dict(), indent=2)
        headers = {
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "CustomSensorAPI/1.0"
        }
        return PlainTextResponse(content=content, headers=headers)
    except Exception as e:
        logger.error(f"Error getting {sensor_type} sensor: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sensors/{sensor_type}/live", response_class=PlainTextResponse)
async def get_live_sensor(sensor_type: str, request: Request):
    if sensor_type not in sensors:
        raise HTTPException(status_code=404, detail=f"Sensor type '{sensor_type}' not found. Available: {list(sensors.keys())}")
    try:
        sensors[sensor_type].update_reading()
        reading = [sensors[sensor_type].get_reading()]
        response = ApiResponse(data=reading, shouldSubscribe="true")
        
        # Create response with ngrok bypass headers
        content = json.dumps(response.dict(), indent=2)
        headers = {
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "CustomSensorAPI/1.0"
        }
        return PlainTextResponse(content=content, headers=headers)
    except Exception as e:
        logger.error(f"Error getting live {sensor_type} sensor: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health", response_class=PlainTextResponse)
async def health_check(request: Request):
    try:
        health_status = {}
        overall_healthy = True
        for sensor_type, sensor in sensors.items():
            try:
                sensor.update_reading()
                reading = sensor.get_reading()
                is_healthy = reading['status'] == 'active'
                health_status[sensor_type] = {
                    'healthy': is_healthy,
                    'last_reading': reading['timestamp'],
                    'sensor_id': reading['sensor_id']
                }
                if not is_healthy:
                    overall_healthy = False
            except Exception as e:
                health_status[sensor_type] = {
                    'healthy': False,
                    'error': str(e)
                }
                overall_healthy = False
        response = {
            'data': [{
                'status': 'healthy' if overall_healthy else 'degraded',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'sensors': health_status
            }],
            'shouldSubscribe': "true"
        }
        # Create response with ngrok bypass headers
        content = json.dumps(response, indent=2)
        headers = {
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "CustomSensorAPI/1.0"
        }
        return PlainTextResponse(content=content, headers=headers)
    except Exception as e:
        logger.error(f"Health check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/config", response_class=PlainTextResponse)
async def get_config(request: Request):
    config = []
    for sensor_type, sensor in sensors.items():
        reading = sensor.get_reading()
        config.append({
            'sensor_id': reading['sensor_id'],
            'sensor_type': reading['sensor_type'],
            'pins': reading['pins'],
            'asset_id': sensor.asset_id
        })
    response = {
        'data': config,
        'shouldSubscribe': "true",
        'api_version': '2.1.0',
        'update_interval': '1_second',
        'connection_type': 'direct_gpio'
    }
    
    # Create response with ngrok bypass headers
    content = json.dumps(response, indent=2)
    headers = {
        "ngrok-skip-browser-warning": "true",
        "User-Agent": "CustomSensorAPI/1.0"
    }
    return PlainTextResponse(content=content, headers=headers)

def continuous_reading():
    """Background task for continuous sensor readings"""
    while True:
        try:
            for sensor in sensors.values():
                sensor.update_reading()
            time.sleep(1)  # Update every second
        except Exception as e:
            logger.error(f"Error in continuous reading: {e}")
            time.sleep(5)

@app.on_event("startup")
async def startup_event():
    """Start background tasks when the app starts"""
    reading_thread = Thread(target=continuous_reading, daemon=True)
    reading_thread.start()
    logger.info("Background reading thread started")
    logger.info("Multi-Sensor API Server started with 5 sensors - Direct GPIO connections")

def cleanup_gpio():
    """Proper GPIO cleanup"""
    try:
        if not SIMULATION_MODE:
            GPIO.cleanup()
            logger.info("GPIO cleaned up successfully")
    except Exception as e:
        logger.error(f"GPIO cleanup error: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Enhanced cleanup"""
    cleanup_gpio()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 

# Fix 7: Install required packages
"""
Run these commands on your Raspberry Pi:

sudo apt update
sudo apt install python3-pip
pip3 install RPi.GPIO
pip3 install Adafruit_DHT
pip3 install fastapi uvicorn

# For DHT sensor, you might also need:
sudo apt install libgpiod2
"""

# Fix 8: Check your wiring connections
"""
Verify these connections:
- Ultrasonic HC-SR04: VCC->5V, GND->GND, Trig->GPIO18, Echo->GPIO24
- MQ-135: VCC->5V, GND->GND, DO->GPIO25, AO->GPIO26 (with RC circuit)
- DHT11: VCC->3.3V, GND->GND, DATA->GPIO22
- LDR: One end to 3.3V, other to GPIO21 and through capacitor to GND
- PIR: VCC->5V, GND->GND, OUT->GPIO23
"""