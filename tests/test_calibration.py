import calibration


def test_build_homography_maps_corners_to_target_rect():
    src_points = [[10, 10], [110, 10], [110, 60], [10, 60]]
    homography = calibration.build_homography(src_points, target_w=1920, target_h=1080)

    tx, ty = calibration.map_point(homography, 10, 10)
    assert (round(tx), round(ty)) == (0, 0)

    tx, ty = calibration.map_point(homography, 110, 60)
    assert (round(tx), round(ty)) == (1920, 1080)


def test_map_point_center_is_roughly_centered():
    src_points = [[0, 0], [100, 0], [100, 100], [0, 100]]
    homography = calibration.build_homography(src_points, target_w=200, target_h=200)
    tx, ty = calibration.map_point(homography, 50, 50)
    assert round(tx) == 100
    assert round(ty) == 100


def test_save_and_load_calibration_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration, "CALIBRATION_PATH", str(tmp_path / "calibration.json"))

    src_points = [[0, 0], [1920, 0], [1920, 1080], [0, 1080]]
    calibration.save_calibration(src_points, target_w=1920, target_h=1080, frame_w=1920, frame_h=1080)

    loaded = calibration.load_calibration()
    assert loaded["src_points"] == src_points
    assert loaded["target_w"] == 1920
    assert loaded["frame_w"] == 1920


def test_load_calibration_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration, "CALIBRATION_PATH", str(tmp_path / "does_not_exist.json"))
    assert calibration.load_calibration() is None


def test_load_calibration_rejects_incomplete_points(tmp_path, monkeypatch):
    path = tmp_path / "calibration.json"
    path.write_text('{"src_points": [[0, 0], [1, 1], [2, 2]], "target_w": 1920, "target_h": 1080}')
    monkeypatch.setattr(calibration, "CALIBRATION_PATH", str(path))

    assert calibration.load_calibration() is None
