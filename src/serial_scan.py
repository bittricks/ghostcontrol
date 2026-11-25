"""
List the available serial ports and try to auto-identify the CH340
adapter (used to connect to the CH9329 module).

The most common CH340 uses VID:PID 1A86:7523. Some clones use 1A86:7522
or 1A86:55D4. When not recognized by VID:PID, we also match on the text
"CH340" in the device description.
"""
import serial.tools.list_ports as list_ports

CH340_VID = 0x1A86
CH340_PIDS = {0x7523, 0x7522, 0x55D4}


def is_ch340(port_info):
    if port_info.vid == CH340_VID and port_info.pid in CH340_PIDS:
        return True
    description = (port_info.description or "") + (port_info.manufacturer or "")
    return "ch340" in description.lower()


def find_ch340_port():
    for port_info in list_ports.comports():
        if is_ch340(port_info):
            return port_info.device
    return None


def main():
    ports = list(list_ports.comports())
    if not ports:
        print("No serial port found.")
        return

    for port_info in ports:
        marker = " <-- looks like the CH340" if is_ch340(port_info) else ""
        vid_pid = (
            f"VID:PID={port_info.vid:04X}:{port_info.pid:04X}"
            if port_info.vid is not None
            else "VID:PID=?"
        )
        print(f"{port_info.device}  {vid_pid}  {port_info.description}{marker}")

    detected = find_ch340_port()
    if detected:
        print(f"\nSuggested port for the CH9329: {detected}")
    else:
        print("\nNo CH340 auto-identified. Check that it's plugged in and use --port manually.")


if __name__ == "__main__":
    main()
