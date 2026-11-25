"""
Direct absolute mapping onto the captured monitor of the target machine.

WARNING: this module is SPECIFIC to the target machine's current setup. If
the monitors change position/resolution/count, update MONITORS with the
output of [System.Windows.Forms.Screen]::AllScreens run ON THE TARGET
MACHINE (or redo the empirical recalibration described below).

CALIBRATION HISTORY
===================
1) Original calibration (3 monitors), via Screen.AllScreens on the target:
     DISPLAY1: X=468,  Y=-1093, 1280x720
     DISPLAY2: X=1920, Y=-13,   1920x1080   <- captured (Excel)
     DISPLAY3: X=0,    Y=0,     1920x1080   <- primary
   resulting virtual bbox: 3840x2173, MON2 offset (1920,1080).

2) That calibration went stale (the target machine started behaving as if
   there were only ONE 1920x1080 monitor from the point of view of the
   CH9329 absolute range — probably the other 2 monitors were
   disconnected/turned off, or the "extend" arrangement became something
   with a total virtual width of ~1920, without changing the resolution of
   the captured monitor itself). Symptom: every click/move landed
   compressed into the bottom-right quadrant of the screen, always with the
   SAME error for the same target (i.e. a systematic scale error, not
   random imprecision nor someone else moving the mouse).

   Recalibrated empirically on 2026-07-02 WITHOUT opening any window on the
   target machine: we sent "move" to several known points (e.g.
   (500,500), (960,540), (100,50)), captured the frame and measured where
   the cursor actually appeared. Linear fit:
     real_x = 0.5 * target_x + 958   (measured at 4 points, error < 15px)
     real_y = 0.5 * target_y + 535
   Solving for the "effective" geometry that produces this relation with
   the old code (MON2_X=1920, VIRTUAL_W=3840) gives exactly
   VIRTUAL_W_real ~= 1920, VIRTUAL_H_real ~= 1080, MON2_X_real ~= 0,
   MON2_Y_real ~= 0 — i.e. the captured monitor today IS the whole area of
   the absolute range (1:1 mapping, no offset).

   If it ever goes back to 3 monitors, restore block (1) above in MONITORS
   and set CAPTURED_MONITOR back.

The CH9329 absolute mode (command 0x04) maps the 0-4095 range onto the
rectangle enclosing ALL monitors (SM_XVIRTUALSCREEN / SM_YVIRTUALSCREEN /
SM_CXVIRTUALSCREEN / SM_CYVIRTUALSCREEN), not just the primary monitor.
This module converts a LOCAL point of the captured monitor (0,0 = top-left
corner) into the parameters build_mouse_absolute_frame expects, reusing
CH9329Controller.move_absolute/click_absolute without modifying them.

Advantage over relative movement: absolute HID reports are not affected by
Windows' "Enhance pointer precision" option (which only alters relative
reports), so control stays accurate without touching the target system's
settings.
"""

# CURRENT geometry (recalibrated 2026-07-02): a single effective 1920x1080
# monitor, no offset — see CALIBRATION HISTORY above.
MONITORS = {
    "DISPLAY2": {"x": 0, "y": 0, "w": 1920, "h": 1080},
}

CAPTURED_MONITOR = "DISPLAY2"


def compute_virtual_bbox(monitors):
    """Bounding box (min_x, min_y, width, height) of the Windows virtual
    desktop area that encloses all the given monitors.

    Accepts any iterable of dicts; materializing into a list is required
    because we iterate more than once (min/max below) and a generator can
    only be traversed once."""
    monitors = list(monitors)
    min_x = min(m["x"] for m in monitors)
    min_y = min(m["y"] for m in monitors)
    max_x = max(m["x"] + m["w"] for m in monitors)
    max_y = max(m["y"] + m["h"] for m in monitors)
    return min_x, min_y, max_x - min_x, max_y - min_y


def monitor_offset_in_virtual(monitor, bbox):
    """Offset of a monitor's top-left corner within the bounding box (origin
    shifted to 0,0)."""
    min_x, min_y = bbox[0], bbox[1]
    return monitor["x"] - min_x, monitor["y"] - min_y


_BBOX = compute_virtual_bbox(MONITORS.values())

# values with the CURRENT geometry (single monitor; with the historical
# 3-monitor geometry these were 3840x2173 and offset 1920,1080)
VIRTUAL_W = _BBOX[2]   # 1920
VIRTUAL_H = _BBOX[3]   # 1080

_MON2 = MONITORS[CAPTURED_MONITOR]
MON2_X, MON2_Y = monitor_offset_in_virtual(_MON2, _BBOX)   # 0, 0
MON2_W = _MON2["w"]    # 1920
MON2_H = _MON2["h"]    # 1080


def to_virtual(rx, ry):
    """Convert (x,y) local to monitor 2 into (x,y) in the virtual space that
    build_mouse_absolute_frame/scale_to_abs must receive together with
    screen_w=VIRTUAL_W, screen_h=VIRTUAL_H. Points outside the monitor are
    clamped to the edge so they never escape to another monitor."""
    rx = max(0, min(MON2_W - 1, rx))
    ry = max(0, min(MON2_H - 1, ry))
    return MON2_X + rx, MON2_Y + ry


def move_absolute_mon2(controller, rx, ry, buttons=0, wheel=0):
    vx, vy = to_virtual(rx, ry)
    controller.move_absolute(vx, vy, VIRTUAL_W, VIRTUAL_H, buttons=buttons, wheel=wheel)


def click_absolute_mon2(controller, rx, ry, button):
    vx, vy = to_virtual(rx, ry)
    controller.click_absolute(vx, vy, VIRTUAL_W, VIRTUAL_H, button=button)
