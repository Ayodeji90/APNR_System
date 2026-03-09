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
- **Web dashboard** (Flask) — dark-themed, responsive
- **Fail-safe** — barrier stays closed on crash; systemd auto-restart
- **Simulator mode** — runs on any machine (no Pi hardware required for development)

---

## Hardware Requirements

| Component | Purpose |
|---|---|
| Raspberry Pi 3B+ | Main processor |
| Pi Camera V2 | Frame capture |
| HC-SR04 | Vehicle presence detection |
| SG90 / MG996R Servo | Barrier arm |
| Relay Module *(optional)* | External gate motor / solenoid |
| 5V/3A Power Supply | Stable power for Pi |
| 5V External Supply | Servo/relay power (share GND with Pi) |

### Wiring

```
Camera       → CSI port

HC-SR04:
  VCC  → 5V
  GND  → GND
  TRIG → GPIO 23
  ECHO → GPIO 24 (via voltage divider 5V → 3.3V!)

Servo:
  Signal → GPIO 18 (PWM)
  VCC    → 5V external
  GND    → common GND

Relay:
  IN  → GPIO 25
  VCC → 5V
  GND → common GND
```

> ⚠ **Important:** Use a voltage divider (two resistors) on the HC-SR04 ECHO pin to step 5V down to 3.3V. This protects the Pi's GPIO.

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
 