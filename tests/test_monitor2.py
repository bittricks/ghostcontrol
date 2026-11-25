import monitor2


def test_virtual_bbox_matches_discovered_setup():
    # geometry recalibrated empirically on 2026-07-02: a single effective
    # 1920x1080 monitor occupying the whole absolute range (see the
    # CALIBRATION HISTORY block in monitor2.py; it used to be 3840x2173)
    assert monitor2.VIRTUAL_W == 1920
    assert monitor2.VIRTUAL_H == 1080


def test_mon2_offset_inside_virtual_bbox():
    # the captured monitor today starts at the origin of the absolute range (0,0)
    assert (monitor2.MON2_X, monitor2.MON2_Y) == (0, 0)
    assert (monitor2.MON2_W, monitor2.MON2_H) == (1920, 1080)


def test_compute_virtual_bbox_generic():
    monitors = [
        {"x": 0, "y": 0, "w": 100, "h": 50},
        {"x": -100, "y": 20, "w": 100, "h": 50},
    ]
    assert monitor2.compute_virtual_bbox(monitors) == (-100, 0, 200, 70)


def test_monitor_offset_in_virtual_generic():
    bbox = (-100, -50, 300, 200)
    monitor = {"x": 0, "y": 0, "w": 100, "h": 100}
    assert monitor2.monitor_offset_in_virtual(monitor, bbox) == (100, 50)


def test_to_virtual_origin_and_far_corner():
    # current geometry: offset (0,0), 1:1 mapping inside the monitor
    assert monitor2.to_virtual(0, 0) == (monitor2.MON2_X, monitor2.MON2_Y)
    assert monitor2.to_virtual(1919, 1079) == (monitor2.MON2_X + 1919, monitor2.MON2_Y + 1079)


def test_to_virtual_clamps_points_outside_monitor():
    # must never escape to another monitor
    assert monitor2.to_virtual(-10, -10) == (monitor2.MON2_X, monitor2.MON2_Y)
    assert monitor2.to_virtual(5000, 5000) == (monitor2.MON2_X + 1919, monitor2.MON2_Y + 1079)


class FakeController:
    def __init__(self):
        self.moves = []
        self.clicks = []

    def move_absolute(self, x, y, screen_w, screen_h, buttons=0, wheel=0):
        self.moves.append((x, y, screen_w, screen_h, buttons, wheel))

    def click_absolute(self, x, y, screen_w, screen_h, button=0):
        self.clicks.append((x, y, screen_w, screen_h, button))


def test_move_absolute_mon2_passes_virtual_space_params():
    controller = FakeController()
    monitor2.move_absolute_mon2(controller, 10, 20)
    vx, vy = monitor2.to_virtual(10, 20)
    assert controller.moves == [(vx, vy, monitor2.VIRTUAL_W, monitor2.VIRTUAL_H, 0, 0)]


def test_click_absolute_mon2_passes_virtual_space_params():
    controller = FakeController()
    monitor2.click_absolute_mon2(controller, 0, 0, button=1)
    vx, vy = monitor2.to_virtual(0, 0)
    assert controller.clicks == [(vx, vy, monitor2.VIRTUAL_W, monitor2.VIRTUAL_H, 1)]
