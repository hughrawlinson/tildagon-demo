import app
import asyncio
from app_components.tokens import label_font_size
from app_components.notification import Notification
from events.input import Buttons, BUTTON_TYPES
from tildagonos import tildagonos

from system.eventbus import eventbus
from system.patterndisplay.events import PatternDisable, PatternEnable


# Hexpansion related imports
from system.hexpansion.header import HexpansionHeader
from system.hexpansion.util import (
    read_hexpansion_header,
    get_hexpansion_block_devices,
    detect_eeprom_addr,
)
from system.hexpansion.events import HexpansionInsertionEvent
import vfs
import os
import asyncio
from system.hexpansion.config import _pin_mapping
from machine import (Pin, I2C)
from tildagon import Pin as ePin

# Motor Driver
PWM_FREQ = 5000
MAX_DUTY = 1023

VERTICAL_OFFSET = label_font_size
H_START = -78
V_START = -58

TICK_MS = 20
POWER_STEP_PER_TICK = 20
LONG_PRESS_MS = 750

USER_TICK_MULTIPLIER = 4

MAX_POWER = 100

# App states
INIT = -1
WARNING = 0
MENU = 1
RECEIVE_INSTR = 2
COUNTDOWN = 3
RUN = 4
DONE = 5
DETECTED = 6        # Hexpansion with EEPROM detected
PROGRAMMING = 7     # Hexpansion EEPROM programming

MINIMISE_VALID_STATES = [0, 1, 2, 5]

DEFAULT_HEX_DRIVE_SLOT = 2
POWER_ENABLE_PIN_INDEX = 0	# First LS pin

class Instruction:
    def __init__(self, press_type: BUTTON_TYPES) -> None:
        self._press_type = press_type
        self._duration = 1
        self.power_plan_iterator = iter([])

    @property
    def press_type(self) -> BUTTON_TYPES:
        return self._press_type

    def inc(self):
        self._duration += 1

    def __str__(self):
        return f"{self.press_type.name} {self._duration}"

    def directional_power_tuple(self, power):
        if self._press_type == BUTTON_TYPES["UP"]:
            return (power, 0, power, 0)
        elif self._press_type == BUTTON_TYPES["DOWN"]:
            return (0, power, 0, power)
        elif self._press_type == BUTTON_TYPES["LEFT"]:
            return (power, 0, 0, power)
        elif self._press_type == BUTTON_TYPES["RIGHT"]:
            return (0, power, power, 0)

    def make_power_plan(self):
        # return collection of tuples of power and their duration
        ramp_up = [(self.directional_power_tuple(p), TICK_MS)
                   for p in range(0, MAX_POWER, POWER_STEP_PER_TICK)]
        power_durations = ramp_up.copy()
        user_power_duration = TICK_MS * USER_TICK_MULTIPLIER * (self._duration-1)
        power_durations.append((self.directional_power_tuple(MAX_POWER), user_power_duration))
        ramp_down = ramp_up.copy()
        ramp_down.reverse()
        power_durations.extend(ramp_down)
        self.power_plan_iterator = iter(power_durations)


class BadgeBotApp(app.App):
    def __init__(self):
        super().__init__()
        self.button_states = Buttons(self)
        self.last_press: BUTTON_TYPES = BUTTON_TYPES["CANCEL"]
        self.long_press_delta = 0

        self.is_scroll = False
        self.scroll_offset = 0

        self.run_countdown_target_ms = 3000
        self.run_countdown_ms = 0

        self.instructions = []
        self.current_instruction = None

        self.current_power_duration = ((0,0,0,0), 0)
        self.power_plan_iter = iter([])

        self.notification = None

        self.status = "Insert HexDrive in Slot 2 to program"
        self.programming_port = DEFAULT_HEX_DRIVE_SLOT
        self.ports_with_blank_eeprom = []
        self.ports_with_hexdrive = []
        eventbus.on_async(
            HexpansionInsertionEvent, self.handle_hexpansion_insertion, self
        )

        # Overall app state
        self.current_state = INIT

    async def handle_hexpansion_insertion(self, event):
        await asyncio.sleep(1)    
        i2c = I2C(event.port)
        # Autodetect eeprom addr
        addr = detect_eeprom_addr(i2c)
        if addr is None:
            print("Scan found no eeproms")
            return
        # Do we have a header?
        header = read_hexpansion_header(i2c, addr)
        if (header is None):
            print(f"Detected eeprom at {hex(addr)}")
            self.ports_with_blank_eeprom.append(event.port)
            return
        elif header.vid == 0xCAFE and header.pid == 0xCBCB:
            # This is ours
            print("Found HexDrive on port", event.port)
            self.current_state = PROGRAMMING
            self.status = f"Found {header.friendly_name} #{header.unique_id}"
            if event.port not in self.ports_with_hexdrive:
                self.ports_with_hexdrive.append(event.port)
            await asyncio.sleep(0.5)          
            # Try creating block devices, one for the whole eeprom,
            # one for the partition with the filesystem on it
            try:
                eep, partition = get_hexpansion_block_devices(i2c, header, addr)
            except RuntimeError as e:
                return
            # TODO CHECK IF UPDATE IS REQUIRED            
            mountpoint = '/fixinghexdrive'
            vfs.mount(partition, mountpoint, readonly=False)
            print(os.listdir(mountpoint))
            self.status = "Mounted filesystem"
            await asyncio.sleep(0.5)
            print("1")
            path = "/" + __file__.rsplit("/", 1)[0] + "/hexdrive.py"
            print("2")
            with open(f"{mountpoint}/app.py", "wt") as appfile:
                print("3")
                with open(path, "rt") as template:
                    print("4")
                    appfile.write(template.read())
            self.status = "Updated application"
            vfs.umount(mountpoint)
            await asyncio.sleep(3)
            self.status = ""
            self.current_state = MENU
            #self.minimise()

    def prepare_eeprom(self, port, i2c, addr):
        # Fill in your desired header info here:
        self.status = "EEPROM initialising..."
        print("Initialising EEPROM @", hex(addr), "on port", port)
        # TODO read EEPROM size and set page size accordingly
        header = HexpansionHeader(
            manifest_version="2024",
            fs_offset=32,
            eeprom_page_size=32,
            eeprom_total_size=64 * 1024 // 8,  # only claim to be 512kbit which is 64kbyte and hence does not use A16.
            vid=0xCAFE,
            pid=0xCBCB,
            unique_id=0x0,
            friendly_name="HexDrive",
        )

        # Determine amount of bytes in internal address
        addr_len = 2 if header.eeprom_total_size > 256 else 1
        print(f"Using {addr_len} bytes for eeprom internal address")
        # Write and read back header
        # write_header is broken for our type of EEPROM so we do it manually
        #write_header(port, header, addr=addr, addr_len=addr_len, page_size=header.eeprom_page_size)
        i2c.writeto(addr, bytes([0, 0]) + header.to_bytes())
        header = read_hexpansion_header(i2c, addr, set_read_addr=True, addr_len=addr_len)
        if header is None:
            self.status = "EEPROM Init Failed"
            raise RuntimeError("EEPROM Init failed")
        # Get block devices
        eep, partition = get_hexpansion_block_devices(i2c, header, addr)
        # Format
        vfs.VfsLfs2.mkfs(partition)
        # And mount!
        vfs.mount(partition, "/eeprom")
        print("EEPROM initialised")
        self.status = "EEPROM initialised"

    def set_pin_out(self, pin):
        # Tildagon(s) (version 1.6) is missing code to set the eGPIO direction to output
        # so we need to update this directly
        try:
            # Use a Try in case access to i2C(7) is blocked for apps in future
            # presumably if this happens then the code will have been updated to
            # handle the GPIO direction correctly anyway.
            i2c = I2C(7)
            config_reg = int.from_bytes(i2c.readfrom_mem(pin[0], 0x04+pin[1], 1), 'little')
            config_reg &= ~(pin[2])
            i2c.writeto_mem(pin[0], 0x04+pin[1], bytes([config_reg]))
        except:
            print("access to I2C(7) blocked")

    # Scan the Hexpansion ports for EEPROMs and HexDrives in case they are already plugged in when we start
    def scan_ports(self):
        for port in range(1, 5):
            i2c = I2C(port)
            addr = detect_eeprom_addr(i2c)
            if addr is not None:
                header = read_hexpansion_header(i2c, addr)
                if header is None:
                    print("Found EEPROM on port", port, "at", hex(addr))
                    self.ports_with_blank_eeprom.append(port)
                elif header.vid == 0xCAFE and header.pid == 0xCBCB:
                    print("Found HexDrive on port", port)
                    self.ports_with_hexdrive.append(port)

    def update(self, delta):
        if self.notification:
            self.notification.update(delta)

        if self.current_state == INIT:
            self.scan_ports()
            if len(self.ports_with_hexdrive) == 0:
                # There are currently no HexDrives plugged in
                if len(self.ports_with_blank_eeprom) == 0:
                    self.current_state = WARNING
                else:    
                    self.current_state = DETECTED
            else:
                self.current_state = MENU
            return    
        # EEPROM initialisation
        # if there are any ports with blank eeproms, initialise them
        if 0 < len(self.ports_with_blank_eeprom):
            # only initialise if in specific port for which button has been pressed TODO
            port = self.ports_with_blank_eeprom.pop(0)
            if (self.programming_port == port):
                # Only initialise the EEPROM on the selected port if it is the specified port
                i2c = I2C(port)
                # Autodetect eeprom addr
                addr = 0x50 # detect_eeprom_addr(i2c)
                if addr is not None:
                    # Do we have a header?
                    header = None # read_hexpansion_header(i2c, addr)
                    if (header is None):
                        self.current_state = PROGRAMMING
                        self.prepare_eeprom(port, i2c, addr)
                        # How to now trigger EEPROM to be programmed?
                        self.current_state = MENU
        if self.button_states.get(BUTTON_TYPES["UP"]):
                # Test Use - enable Hexpansion Power
                print("Enable HexDrive Power")
                power_enable_pin_number = _pin_mapping[self.port]["ls"][POWER_ENABLE_PIN_INDEX]
                HexDrivePowerEnable = ePin(power_enable_pin_number,Pin.OUT)
                # Issue that the Badge Code does not set the IO expander to output mode
                self.set_pin_out(HexDrivePowerEnable.pin)
                HexDrivePowerEnable.value(1)
        if self.button_states.get(BUTTON_TYPES["DOWN"]):
                # Test Use - disable Hexpansion Power
                print("Disable HexDrive Power")
                power_enable_pin_number = _pin_mapping[self.port]["ls"][POWER_ENABLE_PIN_INDEX]
                HexDrivePowerEnable = ePin(power_enable_pin_number,Pin.OUT)
                HexDrivePowerEnable.value(0)                
        if self.button_states.get(BUTTON_TYPES["CANCEL"]) and self.current_state in MINIMISE_VALID_STATES:
            self.button_states.clear()
            eventbus.emit(PatternEnable()) # TODO replace with on lose focus on gain focus
            self.minimise()
        elif self.current_state == MENU:
            # Exit start menu
            if self.button_states.get(BUTTON_TYPES["CONFIRM"]):
                self.current_state = RECEIVE_INSTR
                self.button_states.clear()
        elif self.current_state == WARNING:
            # Exit warning screen
            if self.button_states.get(BUTTON_TYPES["CONFIRM"]):
                self.current_state = MENU
                self.button_states.clear()
        elif self.current_state == RECEIVE_INSTR:
            eventbus.emit(PatternDisable())
            self.clear_leds()
            # Enable/disable scrolling and check for long press
            if self.button_states.get(BUTTON_TYPES["CONFIRM"]):
                if self.long_press_delta == 0:
                    # TODO Move to button up event
                    self.is_scroll = not self.is_scroll
                    self.notification = Notification(f"Scroll {self.is_scroll}")
                self.long_press_delta += delta
                if self.long_press_delta >= LONG_PRESS_MS:
                    self.finalize_instruction()
                    self.current_state = COUNTDOWN
            else:
                # Confirm is not pressed. Reset long_press state
                self.long_press_delta = 0
                # Manage scrolling
                if self.is_scroll:
                    if self.button_states.get(BUTTON_TYPES["DOWN"]):
                        self.scroll_offset -= 1
                    elif self.button_states.get(BUTTON_TYPES["UP"]):
                        self.scroll_offset += 1
                    self.button_states.clear()
                # Instruction button presses
                elif self.button_states.get(BUTTON_TYPES["RIGHT"]):
                    self._handle_instruction_press(BUTTON_TYPES["RIGHT"])
                    self.button_states.clear()
                elif self.button_states.get(BUTTON_TYPES["LEFT"]):
                    self._handle_instruction_press(BUTTON_TYPES["LEFT"])
                    self.button_states.clear()
                elif self.button_states.get(BUTTON_TYPES["UP"]):
                    self._handle_instruction_press(BUTTON_TYPES["UP"])
                    self.button_states.clear()
                elif self.button_states.get(BUTTON_TYPES["DOWN"]):
                    self._handle_instruction_press(BUTTON_TYPES["DOWN"])
                    self.button_states.clear()
                # LED management
                if self.last_press == BUTTON_TYPES["RIGHT"]:
                    tildagonos.leds[2] = (255, 0, 0)
                    tildagonos.leds[3] = (255, 0, 0)
                elif self.last_press == BUTTON_TYPES["LEFT"]:
                    tildagonos.leds[8] = (0, 255, 0)
                    tildagonos.leds[9] = (0, 255, 0)
                elif self.last_press == BUTTON_TYPES["UP"]:
                    tildagonos.leds[12] = (0, 0, 255)
                    tildagonos.leds[1] = (0, 0, 255)
                elif self.last_press == BUTTON_TYPES["DOWN"]:
                    tildagonos.leds[6] = (255, 255, 0)
                    tildagonos.leds[7] = (255, 255, 0)
            tildagonos.leds.write()

        elif self.current_state == COUNTDOWN:
            self.run_countdown_ms += delta
            if self.run_countdown_ms >= self.run_countdown_target_ms:
                self.power_plan_iter = chain(*(instr.power_plan_iterator for instr in self.instructions))
                self.current_state = RUN

        elif self.current_state == RUN:
            print(delta)
            power = self.get_current_power_level(delta)
            if power is None:
                self.current_state = DONE
            print(f"Using power: {power}")

        elif self.current_state == DONE:
            eventbus.emit(PatternEnable())
            if self.button_states.get(BUTTON_TYPES["CONFIRM"]):
                self.reset()

    def _handle_instruction_press(self, press_type: BUTTON_TYPES):
        if self.last_press == press_type:
            self.current_instruction.inc()
        else:
            self.finalize_instruction()
            self.current_instruction = Instruction(press_type)
        self.last_press = press_type

    def reset(self):
        self.current_state = MENU
        self.button_states.clear()
        self.last_press: BUTTON_TYPES = BUTTON_TYPES["CANCEL"]
        self.long_press_delta = 0

        self.is_scroll = False
        self.scroll_offset = 0

        self.run_countdown_target_ms = 3000
        self.run_countdown_ms = 0

        self.instructions = []
        self.current_instruction = None

        self.current_power_duration = ((0,0,0,0), 0)
        self.power_plan_iter = iter([])


    def draw(self, ctx):
        ctx.save()
        ctx.font_size = label_font_size
        # Scroll mode indicator
        if self.is_scroll:
            ctx.rgb(0.1,0,0).rectangle(-120,-120,240,240).fill()
        else:
            ctx.rgb(0,0,0.1).rectangle(-120,-120,240,240).fill()

        if self.current_state == WARNING:
            ctx.rgb(1,1,1).move_to(H_START, V_START + 0*VERTICAL_OFFSET + 20).text("Please buy")
            ctx.rgb(1,1,0).move_to(H_START, V_START + 1*VERTICAL_OFFSET + 20).text("HexDrive")
            ctx.rgb(1,1,1).move_to(H_START, V_START + 2*VERTICAL_OFFSET + 20).text("Hexpansion")
            ctx.rgb(1,1,1).move_to(H_START, V_START + 3*VERTICAL_OFFSET + 20).text("from")
            ctx.rgb(1,1,0).move_to(H_START, V_START + 4*VERTICAL_OFFSET + 20).text("RobotMad")
        elif self.current_state == DETECTED:  
            ctx.rgb(1,1,1).move_to(H_START, V_START + 0*VERTICAL_OFFSET + 20).text("Hexpansion")
            ctx.rgb(1,1,0).move_to(H_START, V_START + 1*VERTICAL_OFFSET + 20).text("Detected")
            ctx.rgb(1,1,1).move_to(H_START, V_START + 2*VERTICAL_OFFSET + 20).text("Program EEPROM")
            ctx.rgb(1,1,1).move_to(H_START, V_START + 3*VERTICAL_OFFSET + 20).text("with HexDrive?")
            #TODO button to confirm - with timeout
        elif self.current_state == PROGRAMMING:
            ctx.text_align = ctx.CENTER
            ctx.rgb(1, 1, 1).move_to(0,0).text(self.status)
        elif self.current_state == MENU:
            ctx.rgb(1,1,1).move_to(H_START, V_START).text("To Program:")
            ctx.rgb(1,1,0).move_to(H_START, V_START + VERTICAL_OFFSET).text("Press C")
            ctx.rgb(1,1,1).move_to(H_START, V_START + 2*VERTICAL_OFFSET + 10).text("When finished:")
            ctx.rgb(1,1,0).move_to(H_START, V_START + 3*VERTICAL_OFFSET + 10).text("Long press C")
        elif self.current_state == RECEIVE_INSTR:
            for i_num, instr in enumerate(["START"] + self.instructions + [self.current_instruction, "END"]):
                ctx.rgb(1,1,0).move_to(H_START, V_START + VERTICAL_OFFSET * (self.scroll_offset + i_num)).text(str(instr))
        elif self.current_state == COUNTDOWN:
            ctx.rgb(1,1,1).move_to(H_START, V_START).text("Running in:")
            countdown_val = (self.run_countdown_target_ms - self.run_countdown_ms) / 1000
            ctx.rgb(1,1,0).move_to(H_START, V_START+VERTICAL_OFFSET).text(str(countdown_val))
        elif self.current_state == RUN:
            ctx.rgb(1,1,1).move_to(H_START, V_START).text("Running power")
            ctx.rgb(1,0,0).move_to(H_START-30, V_START + 2*VERTICAL_OFFSET).text(str(self.current_power_duration))
        elif self.current_state == DONE:
            ctx.rgb(1,1,1).move_to(H_START, V_START).text(f"Complete!")
            ctx.rgb(1,1,1).move_to(H_START, V_START + VERTICAL_OFFSET).text("To restart:")
            ctx.rgb(1,1,0).move_to(H_START, V_START + 2*VERTICAL_OFFSET).text("Press C")
        if self.notification:
            self.notification.draw(ctx)
        ctx.restore()


    def get_current_power_level(self, delta) -> int:
        # takes in delta as ms since last call
        # if delta was > 20... what to do
        if delta >= TICK_MS:
            delta = TICK_MS-1

        current_power, current_duration = self.current_power_duration

        updated_duration = current_duration - delta
        if updated_duration <= 0:
            try:
                next_power, next_duration = next(self.power_plan_iter)
            except StopIteration:
                # returns None when complete
                return None
            next_duration += updated_duration
            self.current_power_duration = next_power, next_duration
            return next_power
        else:
            self.current_power_duration = current_power, updated_duration
            return current_power


    def finalize_instruction(self):
        if self.current_instruction is not None:
            self.current_instruction.make_power_plan()
            self.instructions.append(self.current_instruction)
            if len(self.instructions) >= 5:
                self.scroll_offset -= 1
            self.current_instruction = None

    def clear_leds(self):
        for i in range(0,12):
            tildagonos.leds[i+1] = (0, 0, 0)

def chain(*iterables):
    for iterable in iterables:
        yield from iterable

__app_export__ = BadgeBotApp
