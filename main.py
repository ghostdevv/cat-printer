import asyncio
import threading
import queue
from datetime import datetime
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
import PIL.ImageChops
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from flask import Flask, request, jsonify

# CRC8 table for message integrity
crc8_table = [
    0x00, 0x07, 0x0e, 0x09, 0x1c, 0x1b, 0x12, 0x15, 0x38, 0x3f, 0x36, 0x31,
    0x24, 0x23, 0x2a, 0x2d, 0x70, 0x77, 0x7e, 0x79, 0x6c, 0x6b, 0x62, 0x65,
    0x48, 0x4f, 0x46, 0x41, 0x54, 0x53, 0x5a, 0x5d, 0xe0, 0xe7, 0xee, 0xe9,
    0xfc, 0xfb, 0xf2, 0xf5, 0xd8, 0xdf, 0xd6, 0xd1, 0xc4, 0xc3, 0xca, 0xcd,
    0x90, 0x97, 0x9e, 0x99, 0x8c, 0x8b, 0x82, 0x85, 0xa8, 0xaf, 0xa6, 0xa1,
    0xb4, 0xb3, 0xba, 0xbd, 0xc7, 0xc0, 0xc9, 0xce, 0xdb, 0xdc, 0xd5, 0xd2,
    0xff, 0xf8, 0xf1, 0xf6, 0xe3, 0xe4, 0xed, 0xea, 0xb7, 0xb0, 0xb9, 0xbe,
    0xab, 0xac, 0xa5, 0xa2, 0x8f, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9d, 0x9a,
    0x27, 0x20, 0x29, 0x2e, 0x3b, 0x3c, 0x35, 0x32, 0x1f, 0x18, 0x11, 0x16,
    0x03, 0x04, 0x0d, 0x0a, 0x57, 0x50, 0x59, 0x5e, 0x4b, 0x4c, 0x45, 0x42,
    0x6f, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7d, 0x7a, 0x89, 0x8e, 0x87, 0x80,
    0x95, 0x92, 0x9b, 0x9c, 0xb1, 0xb6, 0xbf, 0xb8, 0xad, 0xaa, 0xa3, 0xa4,
    0xf9, 0xfe, 0xf7, 0xf0, 0xe5, 0xe2, 0xeb, 0xec, 0xc1, 0xc6, 0xcf, 0xc8,
    0xdd, 0xda, 0xd3, 0xd4, 0x69, 0x6e, 0x67, 0x60, 0x75, 0x72, 0x7b, 0x7c,
    0x51, 0x56, 0x5f, 0x58, 0x4d, 0x4a, 0x43, 0x44, 0x19, 0x1e, 0x17, 0x10,
    0x05, 0x02, 0x0b, 0x0c, 0x21, 0x26, 0x2f, 0x28, 0x3d, 0x3a, 0x33, 0x34,
    0x4e, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5c, 0x5b, 0x76, 0x71, 0x78, 0x7f,
    0x6a, 0x6d, 0x64, 0x63, 0x3e, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2c, 0x2b,
    0x06, 0x01, 0x08, 0x0f, 0x1a, 0x1d, 0x14, 0x13, 0xae, 0xa9, 0xa0, 0xa7,
    0xb2, 0xb5, 0xbc, 0xbb, 0x96, 0x91, 0x98, 0x9f, 0x8a, 0x8d, 0x84, 0x83,
    0xde, 0xd9, 0xd0, 0xd7, 0xc2, 0xc5, 0xcc, 0xcb, 0xe6, 0xe1, 0xe8, 0xef,
    0xfa, 0xfd, 0xf4, 0xf3
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
            if device.name == 'MX06':
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
                await self.client.start_notify(NOTIFY_CHARACTERISTIC, self.notification_handler)
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
            chunk = message[i:i + chunk_size]

            # Wait for transmission to be allowed
            while not self.transmit:
                await asyncio.sleep(0.01)

            await self.client.write_gatt_char(PRINTER_CHARACTERISTIC, chunk)
            await asyncio.sleep(delay)

    async def prepare_printer(self, energy=0x2EE0):
        """Initialize printer settings"""
        await self.send_command(SET_QUALITY, [0x33])
        await self.send_command(CONTROL_LATTICE, PRINT_LATTICE)
        energy_bytes = energy.to_bytes(2, 'little')
        await self.send_command(SET_ENERGY, [energy_bytes[0], energy_bytes[1]])
        await self.send_command(DRAWING_MODE, [0])
        await self.send_command(OTHER_FEED_PAPER, IMG_PRINT_SPEED)

    async def finish_printing(self, feed_amount=20):
        """Finish printing and feed paper"""
        await self.send_command(OTHER_FEED_PAPER, BLANK_SPEED)
        if feed_amount > 0:
            feed_bytes = feed_amount.to_bytes(2, 'little')
            await self.send_command(FEED_PAPER, [feed_bytes[0], feed_bytes[1]])
        await self.send_command(CONTROL_LATTICE, FINISH_LATTICE)

    def process_image(self, image_path_or_pil):
        """Convert image to printer format"""
        if isinstance(image_path_or_pil, str):
            image = PIL.Image.open(image_path_or_pil)
        else:
            image = image_path_or_pil

        # Handle transparency
        if image.mode in ('RGBA', 'LA'):
            background = PIL.Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'RGBA':
                background.paste(image, mask=image.split()[-1])
            else:
                background.paste(image, mask=image.split()[-1])
            image = background

        # Resize if too wide
        if image.width > PRINTER_WIDTH:
            height = int(image.height * (PRINTER_WIDTH / image.width))
            image = image.resize((PRINTER_WIDTH, height))

        # Convert to 1-bit black and white
        image = image.convert('1')

        # Pad to printer width if needed
        if image.width < PRINTER_WIDTH:
            padded = PIL.Image.new('1', (PRINTER_WIDTH, image.height), 1)
            padded.paste(image, (0, 0))
            image = padded

        # Rotate 180 degrees so it comes out right-side up (unless in chat mode)
        if not getattr(self, '_chat_mode', False):
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

        lines = ['']
        for word in text.split():
            line = f'{lines[-1]} {word}'.strip()
            if font.getlength(line) <= line_length:
                lines[-1] = line
            else:
                lines.append(word)
        return '\n'.join(lines)

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
        img = PIL.Image.new('RGB', (PRINTER_WIDTH, 2000), color=(255, 255, 255))

        # Try to load font, fall back to default if not found
        try:
            if font_name:
                font = PIL.ImageFont.truetype(font_name, font_size)
            else:
                # Try common system fonts
                for font_path in ["/System/Library/Fonts/Helvetica.ttc",
                                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                                "/Windows/Fonts/arial.ttf"]:
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

    async def print_text(self, text, font_size=40, font_name=None, energy=0x2EE0, feed_amount=20, chat_mode=False):
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
@app.route('/print/text', methods=['POST'])
def api_print_text():
    """API endpoint to print text"""
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'error': 'Missing text parameter'}), 400

        job = {
            'type': 'text',
            'text': data['text'],
            'font_size': data.get('font_size', 40),
            'font_name': data.get('font_name'),
            'energy': data.get('energy', 0x2EE0),
            'feed_amount': data.get('feed_amount', 50),
            'chat_mode': data.get('chat_mode', False)
        }

        print_queue.put(job)
        queue_size = print_queue.qsize()

        return jsonify({
            'status': 'queued',
            'message': f'Print job added to queue (position: {queue_size})'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/print/image', methods=['POST'])
def api_print_image():
    """API endpoint to print image from file upload"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No image file selected'}), 400

        # Load image from uploaded file
        image = PIL.Image.open(file.stream)

        job = {
            'type': 'image',
            'image': image,
            'energy': request.form.get('energy', 0x2EE0, type=int),
            'feed_amount': request.form.get('feed_amount', 50, type=int)
        }

        print_queue.put(job)
        queue_size = print_queue.qsize()

        return jsonify({
            'status': 'queued',
            'message': f'Print job added to queue (position: {queue_size})'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/print/chat', methods=['POST'])
def api_print_chat():
    """API endpoint optimized for chat messages with timestamps"""
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({'error': 'Missing message parameter'}), 400

        # Add timestamp if requested
        message = data['message']
        if data.get('include_timestamp', True):
            timestamp = datetime.now().strftime('%H:%M')
            message = f"[{timestamp}] {message}"

        job = {
            'type': 'text',
            'text': message,
            'font_size': data.get('font_size', 30),  # Smaller default for chat
            'font_name': data.get('font_name'),
            'energy': data.get('energy', 0x2EE0),
            'feed_amount': data.get('feed_amount', 30),  # Less paper feed for chat
            'chat_mode': True  # Always use chat mode
        }

        print_queue.put(job)
        queue_size = print_queue.qsize()

        return jsonify({
            'status': 'queued',
            'message': f'Chat message added to queue (position: {queue_size})',
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/status', methods=['GET'])
def api_status():
    """Get printer and queue status"""
    return jsonify({
        'queue_size': print_queue.qsize(),
        'status': 'running'
    })

@app.route('/queue/clear', methods=['POST'])
def api_clear_queue():
    """Clear the print queue"""
    try:
        while not print_queue.empty():
            print_queue.get()
            print_queue.task_done()
        return jsonify({'status': 'success', 'message': 'Queue cleared'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def run_flask_app():
    """Run Flask app in a separate thread"""
    app.run(host='0.0.0.0', port=5000, debug=False)

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
            if job['type'] == 'text':
                await printer.print_text(
                    text=job['text'],
                    font_size=job['font_size'],
                    font_name=job['font_name'],
                    energy=job['energy'],
                    feed_amount=job['feed_amount'],
                    chat_mode=job['chat_mode']
                )
            elif job['type'] == 'image':
                await printer.print_image(
                    image_path_or_pil=job['image'],
                    energy=job['energy'],
                    feed_amount=job['feed_amount']
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
