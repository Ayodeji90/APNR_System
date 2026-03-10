# 🚗 ANPR Gate System

**Automatic Number Plate Recognition** gate controller for **Raspberry Pi 3B+** with Pi Camera V2, HC-SR04 ultrasonic sensor, servo motor, and relay module.

> Detect vehicle → capture image → detect plate → read characters → decide Allow/Deny → open barrier → log event.

---

## Features

- **Real-time plate detection** using OpenCV contour analysis
- **OCR** via Tesseract with confidence scoring
- **Event-driven state machine** (IDLE → TRIGGERED → CAPTURE → DETECT → OCR → DECIDE → ACTUATE → LOG)
- **Retry logic** with enhanced preprocessing fallback on low-confidence OCR
- **SQLite database** for event logs, vehicle whitelist, and settings
- **Telegram Bot Integration** — real-time notifications with images, remote gate control, and whitelist management via chat
- **Web dashboard** (Flask) — dark-themed, responsive
- **Fail-safe** — barrier stays closed on crash; systemd auto-restart
- **Simulator mode** — runs on any machine (no Pi hardware required for development)

---

## Hardware Requirements

| Component | Model / Spec | Purpose |
|---|---|---|
| Raspberry Pi 3B+ | ARM Cortex-A53, 1 GB RAM | Main processor & orchestrator |
| Pi Camera V2 | Sony IMX219, 8 MP | Frame capture via CSI lane |
| HC-SR04 | 2 cm – 400 cm range | Vehicle proximity detection |
| SG90 / MG996R Servo | SG90 (180°) or MG996R (metal gear) | Physical barrier arm |
| Relay Module | 5V single-channel | External gate motor / solenoid control |
| 5V / 3A Power Supply | ≥ 3 A rating | Stable Pi power (avoid undervoltage) |
| 5V External Supply | Dedicated rail | Servo & relay power (share GND with Pi) |
| Voltage Divider | 1 kΩ + 2 kΩ resistors | Steps HC-SR04 ECHO 5V → 3.3V for GPIO |

---

## Hardware Deep Dive

This section explains **each hardware component** in full detail: its physical role in the gate system, how to wire it, and exactly how the Python driver implements the low-level control that feeds the rest of the software stack.

---

### 1. Raspberry Pi 3B+ — The Main Processor

#### Role
The Pi is the **central brain**. It runs the Python process that continuously polls the sensor, triggers the camera, runs the vision pipeline, makes the access decision, and actuates the barrier — all in a single coherent state machine (`src/state_machine.py`). It also hosts the Flask web dashboard and SQLite database.

Every peripheral connects to the Pi either through:
- **GPIO pins** (sensor, servo, relay) — controlled via `RPi.GPIO`
- **CSI camera port** — dedicated serial lane for the Pi Camera module
- **USB** — optional webcam fallback during development

#### Key specs relevant to this project
| Attribute | Value |
|---|---|
| GPIO voltage | **3.3 V** (⚠ never connect a 5 V signal directly) |
| Max GPIO sink/source current | 16 mA per pin, 50 mA total |
| PWM-capable pins | GPIO 12, 13, 18, 19 (hardware PWM) |
| CSI camera lane | 15-pin ribbon connector |

---

### 2. Pi Camera V2 — Image Capture

#### Role
Mounted above the gate, the Pi Camera V2 captures **still frames** when a vehicle is detected. Multiple frames are captured per trigger event; the sharpest one (highest Laplacian variance) is selected and forwarded to the vision pipeline.

#### Wiring
The Pi Camera connects to the **CSI (Camera Serial Interface) port** — the 15-pin ribbon connector between the USB ports and the HDMI port on the Pi 3B+.

```
Pi Camera V2  →  Pi 3B+ CSI port (15-pin ribbon)

Orientation:
  Blue side of ribbon faces the USB ports (away from HDMI)

Enable in OS:
  sudo raspi-config → Interface Options → Camera → Enable → Reboot
```

> ⚠ **Important:** The ribbon cable is fragile. Insert it fully (it clicks) and ensure the blue stripe faces the correct direction before closing the latch.

#### Programmatic Implementation — `src/camera.py`

The `CameraService` class abstracts the hardware behind a single `capture_best_frame()` method.

**Initialisation** — detects whether `picamera2` is available and configures resolution:

```python
from picamera2 import Picamera2

class CameraService:
    def __init__(self, cfg: AppConfig):
        self._picam = Picamera2()
        config = self._picam.create_still_configuration(
            main={"size": (cfg.camera.resolution_width,
                           cfg.camera.resolution_height)}
        )
        self._picam.configure(config)
        self._picam.start()
        time.sleep(cfg.camera.warmup_seconds)  # let sensor stabilise
```

**Frame capture with sharpness selection** — `picamera2` returns RGB arrays; they are converted to BGR for OpenCV:

```python
def capture_frame(self) -> np.ndarray:
    frame = self._picam.capture_array()
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

def _laplacian_variance(frame: np.ndarray) -> float:
    """Higher = sharper."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()

def capture_best_frame(self) -> np.ndarray:
    best, best_score = None, -1.0
    for _ in range(self.capture_count):
        frame = self.capture_frame()
        score = self._laplacian_variance(frame)
        if score > best_score:
            best_score, best = score, frame
        time.sleep(0.1)
    return best
```

**Fallback (non-Pi machines):** When `picamera2` is not installed, the class transparently falls back to `cv2.VideoCapture(0)` (USB webcam or laptop camera), enabling full development and testing without Pi hardware.

---

### 3. HC-SR04 Ultrasonic Sensor — Vehicle Presence Detection

#### Role
Mounted at bumper height facing the approaching lane, the HC-SR04 acts as a **proximity tripwire**. It emits a 40 kHz ultrasonic pulse and times the echo to calculate distance. When a vehicle enters the detection zone (configurable threshold, default 50 cm), the state machine wakes up and begins the capture cycle.

#### How it works (physics)
```
TRIG pulse (10 µs HIGH) → module emits 8× 40 kHz bursts
Echo pin goes HIGH → you time how long it stays HIGH
Distance (cm) = (echo duration in seconds × 34300) / 2
                          ↑ speed of sound in cm/s
```

#### Wiring

```
HC-SR04 Pin  →  Pi GPIO                Notes
───────────────────────────────────────────────────────────────
VCC          →  5V (Pin 2 or 4)        Module runs on 5V
GND          →  GND (Pin 6)
TRIG         →  GPIO 23 (Pin 16)       3.3V output is enough to trigger
ECHO         →  GPIO 24 (Pin 18)       ⚠ MUST use voltage divider!
```

**Voltage divider for ECHO pin (required):**

```
ECHO pin (5V) ──┬── 1 kΩ ──── GPIO 24 (3.3V safe)
                └── 2 kΩ ──── GND
```

The 1 kΩ / 2 kΩ divider gives: V_out = 5V × 2/(1+2) = **3.33 V** ✓

> ⚠ **Critical:** Connecting the raw 5V ECHO signal directly to a GPIO pin will damage the Pi's I/O bank.

#### Programmatic Implementation — `src/sensor.py`

```python
import RPi.GPIO as GPIO, time

class UltrasonicSensor:
    def __init__(self, cfg):
        self.trigger_pin = cfg.sensor.trigger_pin   # GPIO 23
        self.echo_pin    = cfg.sensor.echo_pin       # GPIO 24
        self.threshold_cm = cfg.sensor.distance_threshold_cm  # 50 cm

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.trigger_pin, GPIO.OUT)
        GPIO.setup(self.echo_pin,    GPIO.IN)
        GPIO.output(self.trigger_pin, False)
        time.sleep(0.05)   # let sensor settle after power-on

    def get_distance(self) -> float:
        # 1. Send 10 µs trigger pulse
        GPIO.output(self.trigger_pin, True)
        time.sleep(0.00001)
        GPIO.output(self.trigger_pin, False)

        # 2. Wait for echo to go HIGH (with 40 ms timeout ≈ 6.8 m)
        pulse_start = time.time()
        while GPIO.input(self.echo_pin) == 0:
            pulse_start = time.time()

        # 3. Wait for echo to go LOW
        pulse_end = time.time()
        while GPIO.input(self.echo_pin) == 1:
            pulse_end = time.time()

        # 4. Calculate distance
        return round((pulse_end - pulse_start) * 34300 / 2, 1)

    def vehicle_present(self) -> bool:
        """Require N consecutive close readings to avoid false triggers."""
        consecutive = 0
        for _ in range(self.confirmation_readings + 2):
            if self.get_distance() < self.threshold_cm:
                consecutive += 1
                if consecutive >= self.confirmation_readings:
                    return True
            else:
                consecutive = 0
            time.sleep(self.reading_interval)
        return False
```

The **confirmation-readings debounce** (default: 3 consecutive readings) prevents false triggers from noise, birds, or brief reflections.

---

### 4. SG90 / MG996R Servo Motor — Physical Barrier Arm

#### Role
The servo is the **physical actuator** that raises and lowers the gate barrier arm. On an ALLOW decision, the servo sweeps from its closed angle (0°) to its open angle (90°), holds, and then automatically returns after a configurable timeout.

- **SG90** — lightweight, plastic gears, suits small model barriers.
- **MG996R** — metal gears, higher torque, suits heavier real barriers.

#### How it works (PWM)
Servos are controlled by a **50 Hz PWM signal**. The duty cycle encodes the target angle:

```
Duty cycle formula: duty = 2.0 + (angle / 180.0) × 10.0

Angle 0°   → duty ≈  2.0 %
Angle 90°  → duty ≈  7.0 %
Angle 180° → duty ≈ 12.0 %
```

#### Wiring

```
Servo Wire   →  Connection                Notes
─────────────────────────────────────────────────────────────
Signal (orange/yellow) → GPIO 18 (Pin 12)   Hardware PWM pin
VCC    (red)           → 5V EXTERNAL RAIL   NOT from Pi 5V
GND    (brown/black)   → Common GND (shared with Pi)
```

> ⚠ **Never power a servo from the Pi's 5V pin.** Servo stall current (SG90: ~360 mA, MG996R: ~900 mA) will drop the Pi voltage and cause crashes or corruption. Use a dedicated 5V supply.

#### Programmatic Implementation — `src/actuator.py`

```python
import RPi.GPIO as GPIO, time, threading

class ActuatorController:
    def __init__(self, cfg):
        self.servo_pin   = cfg.actuator.servo_pin        # GPIO 18
        self.open_angle  = cfg.actuator.servo_open_angle  # 90°
        self.closed_angle = cfg.actuator.servo_closed_angle # 0°

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.servo_pin, GPIO.OUT)
        self._pwm = GPIO.PWM(self.servo_pin, 50)   # 50 Hz
        self._pwm.start(0)
        self._set_servo_angle(self.closed_angle)   # start closed

    def _angle_to_duty(self, angle: int) -> float:
        return 2.0 + (angle / 180.0) * 10.0

    def _set_servo_angle(self, angle: int) -> None:
        duty = self._angle_to_duty(angle)
        self._pwm.ChangeDutyCycle(duty)
        time.sleep(0.5)          # wait for servo to reach position
        self._pwm.ChangeDutyCycle(0)  # stop signal to prevent jitter

    def open_barrier(self) -> None:
        self._set_servo_angle(self.open_angle)
        # Schedule auto-close after open_duration seconds
        timer = threading.Timer(self.open_duration, self.close_barrier)
        timer.daemon = True
        timer.start()

    def close_barrier(self) -> None:
        self._set_servo_angle(self.closed_angle)
```

The **auto-close timer** runs in a daemon thread. If `open_barrier()` is called again before the timer fires, the timer is cancelled and reset, preventing mid-sweep interruptions.

---

### 5. Relay Module — External Gate Motor / Solenoid Control

#### Role
The relay is an **electrically isolated switch** that allows the 3.3V/5V Pi GPIO to control high-voltage/high-current loads — e.g., a 12V gate motor, a 24V electromagnetic solenoid lock, or a commercial gate controller. It is **optional** — the servo alone is sufficient for a model barrier.

#### How it works
A relay module contains an electromechanical or solid-state relay. A small GPIO output signal (3.3V–5V) energises the relay coil, which mechanically closes the high-current contacts, powering the external device. Most commonly used modules are **active-LOW** (energises when GPIO is LOW).

#### Wiring

```
Relay Pin  →  Connection          Notes
─────────────────────────────────────────────────────────────
IN         →  GPIO 25 (Pin 22)    Control signal (LOW = ON for active-LOW modules)
VCC        →  5V (Pi or external)
GND        →  Common GND
COM        →  External supply +
NO         →  Gate motor / solenoid +  (NO = Normally Open)
GND/−      →  Gate motor / solenoid −
```

> ⚠ **Safety:** Always use a flyback (snubber) diode across inductive loads (motors, solenoids) to suppress voltage spikes when the relay opens.

#### Programmatic Implementation — `src/actuator.py` (relay section)

```python
# Inside ActuatorController.__init__()
GPIO.setup(self.relay_pin, GPIO.OUT)
GPIO.output(self.relay_pin, GPIO.LOW)   # ensure off at startup

# Open gate (energise relay)
def _relay_on(self):
    GPIO.output(self.relay_pin, GPIO.HIGH)

# Close gate (de-energise relay)
def _relay_off(self):
    GPIO.output(self.relay_pin, GPIO.LOW)
```

The `ActuatorController` can operate the servo only, the relay only, or both simultaneously depending on the `use_servo` / `use_relay` flags in `config.yaml`. This means you can upgrade the gate hardware without changing any application logic.

---

### 6. Software-Defined Components (No Physical Wiring)

These components run entirely in software on the Pi's CPU and process the image data coming from the camera.

#### 6a. Plate Detector — `src/plate_detector.py`
Uses OpenCV to find rectangular contours in the camera frame that match the aspect ratio of a licence plate (configurable min/max). The best candidate is extracted via a **perspective transform** (`cv2.getPerspectiveTransform`) to correct for camera angle, then cropped and forwarded to the OCR engine.

```python
# Edge detection → contour → filter by 4-vertex polygon + aspect ratio
edges = preprocessor.preprocess_for_detection(frame)
contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
for c in sorted(contours, key=cv2.contourArea, reverse=True)[:30]:
    approx = cv2.approxPolyDP(c, 0.018 * cv2.arcLength(c, True), True)
    if len(approx) == 4:                   # rectangle
        x, y, w, h = cv2.boundingRect(approx)
        if aspect_min <= w/h <= aspect_max:
            plate_crop = four_point_transform(frame, approx)
```

#### 6b. OCR Engine — `src/ocr_engine.py`
Uses **Tesseract** (via `pytesseract`) with a character whitelist (`A-Z0-9`) and Page Segmentation Mode 8 (single word) to read the licence plate text. Confidence is extracted per-word from `image_to_data()`. If first-pass confidence is low, an enhanced preprocessing pipeline (adaptive threshold, morphological ops) is tried automatically.

```python
config = f"--psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
data = pytesseract.image_to_data(image, config=config,
                                 output_type=pytesseract.Output.DICT)
# Normalize: uppercase, strip non-alphanumeric
plate_text = re.sub(r"[^A-Z0-9]", "", raw_text.upper().strip())
```

---

## System Abstraction Layers

The following diagram shows how **each hardware component maps to a software abstraction layer**, and how those layers compose upward through the state machine to the final gate decision.

```
┌─────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                           │
│  src/main.py  ──  Web Dashboard (Flask)  ──  SQLite Database    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ drives
┌───────────────────────────▼─────────────────────────────────────┐
│                    ORCHESTRATION LAYER                          │
│          src/state_machine.py  (ANPRStateMachine)               │
│  IDLE → TRIGGERED → CAPTURE → DETECT → OCR → DECIDE → ACTUATE  │
└──────┬────────────┬────────────┬──────────────┬─────────────────┘
       │            │            │              │
       │ polls      │ triggers   │ sends crop   │ commands
       ▼            ▼            ▼              ▼
┌──────────┐  ┌──────────┐  ┌──────────────────────────┐  ┌────────────┐
│ SENSOR   │  │  CAMERA  │  │    VISION PIPELINE        │  │ ACTUATOR   │
│  LAYER   │  │  LAYER   │  │         LAYER             │  │  LAYER     │
│          │  │          │  │                           │  │            │
│sensor.py │  │camera.py │  │ plate_detector.py         │  │actuator.py │
│          │  │          │  │ preprocessing.py           │  │            │
│ get_     │  │ capture_ │  │ ocr_engine.py             │  │ open/close │
│ distance │  │ best_    │  │ decision_engine.py        │  │ _barrier() │
│ vehicle_ │  │ frame()  │  │                           │  │            │
│ present()│  │          │  │                           │  │            │
└────┬─────┘  └────┬─────┘  └───────────┬───────────────┘  └─────┬──────┘
     │              │                    │                         │
     │ RPi.GPIO     │ picamera2 / OpenCV │ OpenCV + pytesseract    │ RPi.GPIO
     ▼              ▼                    ▼                         ▼
┌──────────┐  ┌──────────┐         ┌──────────┐         ┌─────────────────┐
│ HC-SR04  │  │Pi Camera │         │  Pi CPU  │         │  Servo (GPIO18) │
│Ultrasonic│  │  V2 CSI  │         │(Software)│         │  Relay (GPIO25) │
│ Sensor   │  │          │         │          │         │                 │
│TRIG:GP23 │  │ 15-pin   │         │          │         │  Barrier Arm /  │
│ECHO:GP24 │  │ ribbon   │         │          │         │  Gate Motor     │
└──────────┘  └──────────┘         └──────────┘         └─────────────────┘
                               PHYSICAL HARDWARE
```

### Layer Responsibilities

| Layer | Files | What it does |
|---|---|---|
| **Physical** | GPIO pins, CSI ribbon | Raw electrical signals & photons |
| **Sensor** | `sensor.py` | Converts echo timing into cm; debounces readings |
| **Camera** | `camera.py` | Configures Pi Camera; selects sharpest frame |
| **Vision** | `plate_detector.py`, `preprocessing.py`, `ocr_engine.py` | Finds plate region → reads text → scores confidence |
| **Orchestration** | `state_machine.py` | Drives the full IDLE→LOG cycle; handles retries and fail-safe |
| **Application** | `main.py`, `web/app.py`, `database.py` | Entry point, web dashboard, event persistence |

### How Hardware Talks to the Raspberry Pi

```
Raspberry Pi 3B+
│
├── GPIO Bank (3.3V logic, RPi.GPIO library)
│   ├── GPIO 23  OUT  → HC-SR04 TRIG    (10µs pulse to trigger sonar)
│   ├── GPIO 24  IN   ← HC-SR04 ECHO    (pulse width = distance ÷ sounds speed)
│   │                   [via 1kΩ/2kΩ voltage divider — 5V to 3.3V]
│   ├── GPIO 18  OUT  → Servo Signal     (50 Hz PWM, duty cycle = angle)
│   └── GPIO 25  OUT  → Relay IN        (HIGH/LOW to open/close gate)
│
└── CSI Port (Camera Serial Interface 2 — ribbon cable)
    └── Pi Camera V2  →  Dedicated MIPI CSI-2 lane  →  Pi's VideoCore GPU
                         (raw Bayer data → ISP → RGB/YUV → picamera2 array)
```

### Decision Flow (End-to-End)

```
Vehicle enters lane
        ↓
[HC-SR04] Distance < threshold for N readings?
        ↓ YES
[Camera] Capture best_frame (sharpest of capture_count frames)
        ↓
[PlateDetector] Find 4-vertex contour with plate aspect ratio
                → perspective-correct crop
        ↓
[OcrEngine] Run Tesseract on crop → raw text + confidence
            If confidence < threshold → retry with enhanced preprocessing
            If still failing → retry full capture (up to max_retries)
        ↓
[DecisionEngine] Is plate in whitelist DB?
                 Is confidence sufficient?
                 ↓ ALLOW              ↓ DENY / UNKNOWN
[ActuatorController]   Servo → 90°    Servo stays at 0°
                       Relay → ON     Relay stays OFF
                       Auto-close timer armed
        ↓
[Database] Log event: plate, decision, confidence, image path, timestamp
        ↓
Return to IDLE
```

> ⚠ **Important:** Use a voltage divider (two resistors) on the HC-SR04 ECHO pin to step 5V down to 3.3V. This protects the Pi's GPIO.

---

---

## Telegram Bot Integration

The ANPR system includes a built-in Telegram bot that provides real-time notifications and allows you to control the gate remotely.

### 1. Create a Telegram Bot
1.  Open Telegram and search for **@BotFather**.
2.  Send the command `/newbot`.
3.  Follow the instructions to name your bot and give it a username.
4.  BotFather will give you an **API Token**. Copy this; you'll need it for your configuration.
5.  Search for your bot by its username and click **Start**.

### 2. Get Your Chat ID
The system only accepts commands from authorized Chat IDs.
1.  Start a conversation with your bot.
2.  Visit `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in your browser.
3.  Look for the `"chat":{"id":123456789...}` section in the JSON response. That number is your Chat ID.

### 3. Configuration
Edit your `config.yaml` to enable the bot:

```yaml
telegram:
  enabled: true
  bot_token: "PASTE_YOUR_TOKEN_HERE"
  allowed_chat_ids: [123456789]  # Add your Chat ID here
  notify_on_allow: true
  notify_on_deny: true
  notify_on_unknown: true
  send_image: true
```

### 4. Bot Commands
| Command | Description |
|---|---|
| `/start` | Show help and command list |
| `/status` | Current system state, barrier status, and uptime |
| `/last_event` | Details of the most recent plate detection |
| `/snapshot` | Capture a live frame from the camera and send it |
| `/open_gate` | Manually raise the barrier |
| `/close_gate` | Manually lower the barrier |
| `/add_plate <ABC123>` | Add a plate to the whitelist |
| `/remove_plate <ABC123>` | Remove a plate from the whitelist |
| `/list_plates` | List all whitelisted vehicles |

---

## Installation

### 1. Prerequisites (Raspberry Pi)

```bash
sudo apt update && sudo apt install -y \
    python3-pip python3-venv \
    tesseract-ocr \
    libopencv-dev

# Enable camera
sudo raspi-config  # → Interface Options → Camera → Enable
```

### 2. Clone & Install

```bash
cd ~
git clone <your-repo-url> ANPR_System
cd ANPR_System

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Pi-specific packages (only on Raspberry Pi)
pip install RPi.GPIO picamera2 gpiozero
```

### 3. Configure

Edit `config.yaml` to set your GPIO pins, thresholds, and preferences.

---

## Usage

### Run the ANPR system

```bash
cd ~/ANPR_System
source venv/bin/activate
python -m src.main
```

### Run the web dashboard

```bash
python -m web.app
# Open http://<pi-ip>:5000 in your browser
```

### Run tests

```bash
python -m pytest tests/ -v
```

---

## Systemd Services (Auto-start on Boot)

```bash
# Copy service files
sudo cp systemd/anpr_core.service /etc/systemd/system/
sudo cp systemd/anpr_web.service /etc/systemd/system/

# Edit paths in the service files if needed
sudo nano /etc/systemd/system/anpr_core.service

# Enable & start
sudo systemctl daemon-reload
sudo systemctl enable anpr_core anpr_web
sudo systemctl start anpr_core anpr_web

# Check status
sudo systemctl status anpr_core
```

---

## Project Structure

```
ANPR_System/
├── config.yaml              # Runtime configuration
├── requirements.txt         # Python dependencies
├── systemd/                 # systemd service files
│   ├── anpr_core.service
│   └── anpr_web.service
├── data/                    # Created at runtime
│   ├── db/anpr.db
│   └── events/YYYY-MM-DD/
├── src/
│   ├── config.py            # YAML config loader
│   ├── database.py          # SQLite schema + CRUD
│   ├── sensor.py            # HC-SR04 driver
│   ├── actuator.py          # Servo + Relay control
│   ├── camera.py            # Pi Camera capture
│   ├── preprocessing.py     # Image preprocessing
│   ├── plate_detector.py    # OpenCV plate detection
│   ├── ocr_engine.py        # Tesseract OCR
│   ├── decision_engine.py   # Allow/Deny logic
│   ├── state_machine.py     # Workflow orchestrator
│   └── main.py              # Entry point
├── web/
│   ├── app.py               # Flask dashboard
│   ├── templates/           # HTML pages
│   └── static/style.css     # Dark theme CSS
└── tests/                   # pytest suite
```

---

## Configuration Reference

All settings live in `config.yaml`:

| Section | Key | Default | Description |
|---|---|---|---|
| `sensor` | `distance_threshold_cm` | 50 | Trigger capture below this distance |
| `sensor` | `confirmation_readings` | 3 | Consecutive readings to confirm |
| `detection` | `min_detection_confidence` | 0.5 | Minimum plate detection score |
| `detection` | `min_ocr_confidence` | 60 | Minimum OCR confidence (0–100) |
| `detection` | `max_retries` | 3 | Retry capture on failure |
| `actuator` | `open_duration_sec` | 10 | Auto-close barrier after N seconds |
| `actuator` | `servo_open_angle` | 90 | Barrier open position |
| `ocr` | `engine` | tesseract | OCR engine (tesseract) |

---

## Tech Stack

- **Python 3** — core language
- **OpenCV** — image processing + plate detection
- **pytesseract** — OCR engine
- **Flask** — web dashboard
- **SQLite** — local database
- **RPi.GPIO** — hardware control (Pi only)

---

## License

MIT
 