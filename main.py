import asyncio
import queue
import threading
from datetime import datetime

import PIL.Image
import PIL.ImageChops
import PIL.ImageDraw
import PIL.ImageFont
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from flask import Flask, jsonify, request
from flask_cors import CORS

# CRC8 table for message integrity
crc8_table = [
    0x00,
    0x07,
    0x0E,
    0x09,
    0x1C,
    0x1B,
    0x12,
    0x15,
    0x38,
    0x3F,
    0x36,
    0x31,
    0x24,
    0x23,
    0x2A,
    0x2D,
    0x70,
    0x77,
    0x7E,
    0x79,
    0x6C,
    0x6B,
    0x62,
    0x65,
    0x48,
    0x4F,
    0x46,
    0x41,
    0x54,
    0x53,
    0x5A,
    0x5D,
    0xE0,
    0xE7,
    0xEE,
    0xE9,
    0xFC,
    0xFB,
    0xF2,
    0xF5,
    0xD8,
    0xDF,
    0xD6,
    0xD1,
    0xC4,
    0xC3,
    0xCA,
    0xCD,
    0x90,
    0x97,
    0x9E,
    0x99,
    0x8C,
    0x8B,
    0x82,
    0x85,
    0xA8,
    0xAF,
    0xA6,
    0xA1,
    0xB4,
    0xB3,
    0xBA,
    0xBD,
    0xC7,
    0xC0,
    0xC9,
    0xCE,
    0xDB,
    0xDC,
    0xD5,
    0xD2,
    0xFF,
    0xF8,
    0xF1,
    0xF6,
    0xE3,
    0xE4,
    0xED,
    0xEA,
    0xB7,
    0xB0,
    0xB9,
    0xBE,
    0xAB,
    0xAC,
    0xA5,
    0xA2,
    0x8F,
    0x88,
    0x81,
    0x86,
    0x93,
    0x94,
    0x9D,
    0x9A,
    0x27,
    0x20,
    0x29,
    0x2E,
    0x3B,
    0x3C,
    0x35,
    0x32,
    0x1F,
    0x18,
    0x11,
    0x16,
    0x03,
    0x04,
    0x0D,
    0x0A,
    0x57,
    0x50,
    0x59,
    0x5E,
    0x4B,
    0x4C,
    0x45,
    0x42,
    0x6F,
    0x68,
    0x61,
    0x66,
    0x73,
    0x74,
    0x7D,
    0x7A,
    0x89,
    0x8E,
    0x87,
    0x80,
    0x95,
    0x92,
    0x9B,
    0x9C,
    0xB1,
    0xB6,
    0xBF,
    0xB8,
    0xAD,
    0xAA,
    0xA3,
    0xA4,
    0xF9,
    0xFE,
    0xF7,
    0xF0,
    0xE5,
    0xE2,
    0xEB,
    0xEC,
    0xC1,
    0xC6,
    0xCF,
    0xC8,
    0xDD,
    0xDA,
    0xD3,
    0xD4,
    0x69,
    0x6E,
    0x67,
    0x60,
    0x75,
    0x72,
    0x7B,
    0x7C,
    0x51,
    0x56,
    0x5F,
    0x58,
    0x4D,
    0x4A,
    0x43,
    0x44,
    0x19,
    0x1E,
    0x17,
    0x10,
    0x05,
    0x02,
    0x0B,
    0x0C,
    0x21,
    0x26,
    0x2F,
    0x28,
    0x3D,
    0x3A,
    0x33,
    0x34,
    0x4E,
    0x49,
    0x40,
    0x47,
    0x52,
    0x55,
    0x5C,
    0x5B,
    0x76,
    0x71,
    0x78,
    0x7F,
    0x6A,
    0x6D,
    0x64,
    0x63,
    0x3E,
    0x39,
    0x30,
    0x37,
    0x22,
    0x25,
    0x2C,
    0x2B,
    0x06,
    0x01,
    0x08,
    0x0F,
    0x1A,
    0x1D,
    0x14,
    0x13,
    0xAE,
    0xA9,
    0xA0,
    0xA7,
    0xB2,
    0xB5,
    0xBC,
    0xBB,
    0x96,
    0x91,
    0x98,
    0x9F,
    0x8A,
    0x8D,
    0x84,
    0x83,
    0xDE,
    0xD9,
    0xD0,
    0xD7,
    0xC2,
    0xC5,
    0xCC,
    0xCB,
    0xE6,
    0xE1,
    0xE8,
    0xEF,
    0xFA,
    0xFD,
    0xF4,
    0xF3,
]


def crc8(data):
    crc = 0
    for byte in data:
        crc = crc8_table[(crc ^ byte) & 0xFF]
    return crc & 0xFF


def format_message(command, data):
    """Format message according to printer protocol"""
    message = [0x51, 0x78, command, 0x00, len(data), 0x00] + data + [crc8(data), 0xFF]
    return bytes(message)


# Printer constants
PRINTER_WIDTH = 384
PRINTER_CHARACTERISTIC = "0000AE01-0000-1000-8000-00805F9B34FB"
NOTIFY_CHARACTERISTIC = "0000AE02-0000-1000-8000-00805F9B34FB"

# Commands
DRAW_BITMAP = 0xA2
FEED_PAPER = 0xA1
SET_QUALITY = 0xA4
CONTROL_LATTICE = 0xA6
DRAWING_MODE = 0xBE
OTHER_FEED_PAPER = 0xBD
SET_ENERGY = 0xAF

# Constants
PRINT_LATTICE = [0xAA, 0x55, 0x17, 0x38, 0x44, 0x5F, 0x5F, 0x5F, 0x44, 0x38, 0x2C]
FINISH_LATTICE = [0xAA, 0x55, 0x17, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x17]
IMG_PRINT_SPEED = [0x05]
BLANK_SPEED = [0x05]

# Global print queue and Flask app
print_queue = queue.Queue()
app = Flask(__name__)
CORS(app)


class CatPrinter:
    def __init__(self):
        self.client = None
        self.device = None
        self.transmit = True

    async def find_printer(self, timeout=10):
        """Find and connect to MX06 printer"""
        print("Scanning for printer...")

        devices = await BleakScanner.discover(timeout=timeout)

        for device in devices:
            if device.name == "MX06":
                self.device = device
                break

        if not self.device:
            raise BleakError("No MX06 printer found")

        print(f"Found printer: {self.device.address}")

    async def connect(self, retries=3):
        """Connect to printer with retry logic"""
        for attempt in range(retries):
            try:
                if not self.device:
                    await self.find_printer()

                print(f"Connecting to printer (attempt {attempt + 1})...")
                self.client = BleakClient(self.device)
                await self.client.connect()
                await self.client.start_notify(
                    NOTIFY_CHARACTERISTIC, self.notification_handler
                )
                print("Connected successfully!")
                return True

            except Exception as e:
                print(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(2)

        return False

    def notification_handler(self, sender, data):
        """Handle printer notifications for flow control"""
        if len(data) >= 3:
            # XOff - pause transmission
            if data[2] == 0xAE and len(data) > 6 and data[6] == 0x10:
                self.transmit = False
                print("Printer paused transmission")
            # XOn - resume transmission
            elif data[2] == 0xAE and len(data) > 6 and data[6] == 0x00:
                self.transmit = True
                print("Printer resumed transmission")

    async def send_command(self, command, data, delay=0.002):
        """Send command to printer with flow control"""
        if not self.client or not self.client.is_connected:
            raise BleakError("Not connected to printer")

        message = format_message(command, data)

        # Send in chunks with flow control
        chunk_size = 100
        for i in range(0, len(message), chunk_size):
            chunk = message[i : i + chunk_size]

            # Wait for transmission to be allowed
            while not self.transmit:
                await asyncio.sleep(0.01)

            await self.client.write_gatt_char(PRINTER_CHARACTERISTIC, chunk)
            await asyncio.sleep(delay)

    async def prepare_printer(self, energy=0x2EE0):
        """Initialize printer settings"""
        await self.send_command(SET_QUALITY, [0x33])
        await self.send_command(CONTROL_LATTICE, PRINT_LATTICE)
        energy_bytes = energy.to_bytes(2, "little")
        await self.send_command(SET_ENERGY, [energy_bytes[0], energy_bytes[1]])
        await self.send_command(DRAWING_MODE, [0])
        await self.send_command(OTHER_FEED_PAPER, IMG_PRINT_SPEED)

    async def finish_printing(self, feed_amount=20):
        """Finish printing and feed paper"""
        await self.send_command(OTHER_FEED_PAPER, BLANK_SPEED)
        if feed_amount > 0:
            feed_bytes = feed_amount.to_bytes(2, "little")
            await self.send_command(FEED_PAPER, [feed_bytes[0], feed_bytes[1]])
        await self.send_command(CONTROL_LATTICE, FINISH_LATTICE)

    def process_image(self, image_path_or_pil):
        """Convert image to printer format"""
        if isinstance(image_path_or_pil, str):
            image = PIL.Image.open(image_path_or_pil)
        else:
            image = image_path_or_pil

        # Handle transparency
        if image.mode in ("RGBA", "LA"):
            background = PIL.Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "RGBA":
                background.paste(image, mask=image.split()[-1])
            else:
                background.paste(image, mask=image.split()[-1])
            image = background

        # Scale to full printer width, maintaining aspect ratio
        if image.width != PRINTER_WIDTH:
            height = int(image.height * (PRINTER_WIDTH / image.width))
            image = image.resize((PRINTER_WIDTH, height), PIL.Image.LANCZOS)

        # Convert to 1-bit black and white
        image = image.convert("1")

        # Rotate 180 degrees so it comes out right-side up (unless in chat mode)
        if not getattr(self, "_chat_mode", False):
            image = image.rotate(180)

        return image

    async def print_image(self, image_path_or_pil, energy=0x2EE0, feed_amount=20):
        """Print an image"""
        if not self.client or not self.client.is_connected:
            await self.connect()

        image = self.process_image(image_path_or_pil)

        print(f"Printing image: {image.width}x{image.height}")

        await self.prepare_printer(energy)

        # Send image data line by line
        for y in range(image.height):
            line_data = []
            bit = 0

            # Pack 8 pixels per byte
            for x in range(image.width):
                if bit % 8 == 0:
                    line_data.append(0x00)

                line_data[bit // 8] >>= 1
                if not image.getpixel((x, y)):  # Black pixel
                    line_data[bit // 8] |= 0x80

                bit += 1

            await self.send_command(DRAW_BITMAP, line_data)

        await self.finish_printing(feed_amount)
        print("Print complete!")

    def get_wrapped_text(self, text, font, line_length):
        """Wrap text to fit within line length"""
        if font.getlength(text) <= line_length:
            return text

        lines = [""]
        for word in text.split():
            line = f"{lines[-1]} {word}".strip()
            if font.getlength(line) <= line_length:
                lines[-1] = line
            else:
                lines.append(word)
        return "\n".join(lines)

    def trim_image(self, image):
        """Trim whitespace from image"""
        bg = PIL.Image.new(image.mode, image.size, (255, 255, 255))
        diff = PIL.ImageChops.difference(image, bg)
        diff = PIL.ImageChops.add(diff, diff, 2.0)
        bbox = diff.getbbox()
        if bbox:
            return image.crop((bbox[0], bbox[1], bbox[2], bbox[3] + 10))
        return image

    def create_text_image(self, text, font_size=40, font_name=None):
        """Create a PIL image from text"""
        # Create a large canvas to start
        img = PIL.Image.new("RGB", (PRINTER_WIDTH, 2000), color=(255, 255, 255))

        # Try to load font, fall back to default if not found
        try:
            if font_name:
                font = PIL.ImageFont.truetype(font_name, font_size)
            else:
                # Try common system fonts
                for font_path in [
                    "/System/Library/Fonts/Helvetica.ttc",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/Windows/Fonts/arial.ttf",
                ]:
                    try:
                        font = PIL.ImageFont.truetype(font_path, font_size)
                        break
                    except:
                        continue
                else:
                    # Fall back to default font
                    font = PIL.ImageFont.load_default()
        except:
            font = PIL.ImageFont.load_default()

        draw = PIL.ImageDraw.Draw(img)

        # Wrap text lines
        lines = []
        for line in text.splitlines():
            lines.append(self.get_wrapped_text(line, font, PRINTER_WIDTH - 20))
        wrapped_text = "\n".join(lines)

        # Draw text
        draw.text((10, 10), wrapped_text, fill=(0, 0, 0), font=font)

        # Trim to actual content
        return self.trim_image(img)

    async def print_text(
        self,
        text,
        font_size=40,
        font_name=None,
        energy=0x2EE0,
        feed_amount=20,
        chat_mode=False,
    ):
        """Print text with specified font size"""
        self._chat_mode = chat_mode
        text_image = self.create_text_image(text, font_size, font_name)
        await self.print_image(text_image, energy, feed_amount)

    async def disconnect(self):
        """Disconnect from printer"""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("Disconnected from printer")


# Flask API routes
@app.route("/print/text", methods=["POST"])
def api_print_text():
    """API endpoint to print text"""
    try:
        data = request.get_json()
        if not data or "text" not in data:
            return jsonify({"error": "Missing text parameter"}), 400

        job = {
            "type": "text",
            "text": data["text"],
            "font_size": data.get("font_size", 40),
            "font_name": data.get("font_name"),
            "energy": data.get("energy", 0x2EE0),
            "feed_amount": data.get("feed_amount", 50),
            "chat_mode": data.get("chat_mode", False),
        }

        print_queue.put(job)
        queue_size = print_queue.qsize()

        return jsonify(
            {
                "status": "queued",
                "message": f"Print job added to queue (position: {queue_size})",
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/print/image", methods=["POST"])
def api_print_image():
    """API endpoint to print image from file upload"""
    try:
        if "image" not in request.files:
            return jsonify({"error": "No image file provided"}), 400

        file = request.files["image"]
        if file.filename == "":
            return jsonify({"error": "No image file selected"}), 400

        # Load image from uploaded file
        # Call .load() to force PIL to read all pixel data while the
        # request stream is still open; without this the stream closes
        # before the queue processor runs.
        image = PIL.Image.open(file.stream)
        image.load()

        job = {
            "type": "image",
            "image": image,
            "energy": request.form.get("energy", 0x2EE0, type=int),
            "feed_amount": request.form.get("feed_amount", 50, type=int),
        }

        print_queue.put(job)
        queue_size = print_queue.qsize()

        return jsonify(
            {
                "status": "queued",
                "message": f"Print job added to queue (position: {queue_size})",
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/print/chat", methods=["POST"])
def api_print_chat():
    """API endpoint optimized for chat messages with timestamps"""
    try:
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Missing message parameter"}), 400

        # Add timestamp if requested
        message = data["message"]
        if data.get("include_timestamp", True):
            timestamp = datetime.now().strftime("%H:%M")
            message = f"[{timestamp}] {message}"

        job = {
            "type": "text",
            "text": message,
            "font_size": data.get("font_size", 30),  # Smaller default for chat
            "font_name": data.get("font_name"),
            "energy": data.get("energy", 0x2EE0),
            "feed_amount": data.get("feed_amount", 30),  # Less paper feed for chat
            "chat_mode": True,  # Always use chat mode
        }

        print_queue.put(job)
        queue_size = print_queue.qsize()

        return jsonify(
            {
                "status": "queued",
                "message": f"Chat message added to queue (position: {queue_size})",
                "timestamp": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/status", methods=["GET"])
def api_status():
    """Get printer and queue status"""
    return jsonify({"queue_size": print_queue.qsize(), "status": "running"})


@app.route("/queue/clear", methods=["POST"])
def api_clear_queue():
    """Clear the print queue"""
    try:
        while not print_queue.empty():
            print_queue.get()
            print_queue.task_done()
        return jsonify({"status": "success", "message": "Queue cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_flask_app():
    """Run Flask app in a separate thread"""
    app.run(host="0.0.0.0", port=5000, debug=False)


async def process_print_queue():
    """Process print jobs from the queue"""
    printer = CatPrinter()

    print("Print queue processor started")

    while True:
        try:
            # Get job from queue (blocking with timeout)
            try:
                job = print_queue.get(timeout=1)
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue

            print(f"Processing job: {job['type']}")

            # Connect to printer if not connected
            if not printer.client or not printer.client.is_connected:
                await printer.connect()

            # Process the job based on type
            if job["type"] == "text":
                await printer.print_text(
                    text=job["text"],
                    font_size=job["font_size"],
                    font_name=job["font_name"],
                    energy=job["energy"],
                    feed_amount=job["feed_amount"],
                    chat_mode=job["chat_mode"],
                )
            elif job["type"] == "image":
                await printer.print_image(
                    image_path_or_pil=job["image"],
                    energy=job["energy"],
                    feed_amount=job["feed_amount"],
                )

            print("Job completed successfully")
            print_queue.task_done()

        except Exception as e:
            print(f"Error processing job: {e}")
            # Still mark task as done to prevent queue from hanging
            try:
                print_queue.task_done()
            except:
                pass

            # Wait a bit before trying next job
            await asyncio.sleep(2)


async def main():
    """Run both Flask API server and print queue processor"""
    print("Starting Cat Printer Server...")

    # Start Flask app in a separate thread
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    print("API server started on http://0.0.0.0:5000")

    # Run the print queue processor
    await process_print_queue()


if __name__ == "__main__":
    asyncio.run(main())
