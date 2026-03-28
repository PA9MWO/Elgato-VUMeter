import libusb_package
import os
import sys
import time
import warnings
import numpy as np
from collections import deque

# --- 1. THE FOOLPROOF WARNING SILENCER ---
import numpy
numpy.fromstring = numpy.frombuffer 

try:
    from soundcard.mediafoundation import SoundcardRuntimeWarning
    warnings.filterwarnings("ignore", category=SoundcardRuntimeWarning)
except ImportError:
    warnings.filterwarnings("ignore", message=".*discontinuity.*")

# --- 2. LIBRARIES ---
import soundcard as sc 
from PIL import Image
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

# --- 3. USB SETUP ---
libusb_path = os.path.dirname(libusb_package.__file__)
if sys.platform == 'win32':
    os.add_dll_directory(libusb_path)

# --- 4. CONFIG ---
NUM_SEGMENTS = 8
LEFT_START_KEY = 8    
RIGHT_START_KEY = 16  
COLORS = ["#00FF00"] * 4 + ["#FFFF00"] * 2 + ["#FF0000"] * 2 
NOTIFICATION_COLOR = "#0000FF" # Deep Blue flash for device change

HISTORY_SIZE = 40 
volume_history = deque(maxlen=HISTORY_SIZE)
MIN_SENSITIVITY = 0.05 
FALL_SPEED = 0.35      

def create_solid_image(deck, color):
    img = Image.new("RGB", (72, 72), color)
    return PILHelper.to_native_format(deck, img)

def flash_notification(deck, color_img):
    """Flashes the VU meter keys to signal a device change."""
    for _ in range(2):
        for i in range(NUM_SEGMENTS):
            deck.set_key_image(LEFT_START_KEY + i, color_img)
            deck.set_key_image(RIGHT_START_KEY + i, color_img)
        time.sleep(0.15)
        deck.reset()
        time.sleep(0.1)

def get_loopback_device():
    try:
        speaker = sc.default_speaker()
        mics = sc.all_microphones(include_loopback=True)
        return next(m for m in mics if m.name == speaker.name)
    except Exception:
        return None

def main():
    deck = None
    try:
        decks = DeviceManager().enumerate()
        if not decks: return
        deck = decks[0]; deck.open(); deck.reset()

        solid_images = [create_solid_image(deck, c) for c in COLORS]
        notify_image = create_solid_image(deck, NOTIFICATION_COLOR)

        current_l_display, current_r_display = 0.0, 0.0
        
        last_device_check = 0
        current_mic = get_loopback_device()
        
        if not current_mic: return

        print(f"Monitoring: {current_mic.name}")

        while True:
            try:
                flash_notification(deck, notify_image)
                
                with current_mic.recorder(samplerate=48000, channels=2) as mic:
                    while True:
                        if time.time() - last_device_check > 2.0:
                            check_mic = get_loopback_device()
                            if check_mic and check_mic.name != current_mic.name:
                                print(f"Output changed to: {check_mic.name}")
                                current_mic = check_mic
                                break 
                            last_device_check = time.time()

                        raw_data = mic.record(numframes=2048) 
                        data = np.nan_to_num(raw_data, nan=0.0)

                        if data.ndim == 2 and data.shape[1] >= 2:
                            l_vol = np.mean(np.abs(data[:, 0]))
                            r_vol = np.mean(np.abs(data[:, 1]))
                        else:
                            l_vol = r_vol = np.mean(np.abs(data.flatten()))
                        
                        volume_history.append(max(l_vol, r_vol))
                        current_sensitivity = max(max(volume_history), MIN_SENSITIVITY)

                        target_l = (l_vol * NUM_SEGMENTS / current_sensitivity)
                        target_r = (r_vol * NUM_SEGMENTS / current_sensitivity)

                        # Smoothing (Attack is instant, Fall is controlled)
                        current_l_display = target_l if target_l > current_l_display else current_l_display - FALL_SPEED
                        current_r_display = target_r if target_r > current_r_display else current_r_display - FALL_SPEED

                        # Final Integer Levels
                        l_lvl_int, r_lvl_int = int(current_l_display), int(current_r_display)

                        for i in range(NUM_SEGMENTS):
                            l_key, r_key = LEFT_START_KEY + i, RIGHT_START_KEY + i
                            
                            # Left Channel Draw
                            deck.set_key_image(l_key, solid_images[i] if i < l_lvl_int else None)

                            # Right Channel Draw
                            deck.set_key_image(r_key, solid_images[i] if i < r_lvl_int else None)

                        time.sleep(0.005)

            except Exception:
                time.sleep(1.0)
                current_mic = get_loopback_device()

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        if deck:
            deck.reset(); deck.close()

if __name__ == "__main__":
    main()