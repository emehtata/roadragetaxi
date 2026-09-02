from theroadragetrip.residents import ResidentManager


def test_resident_lod_uses_distance_bands():
    manager = ResidentManager()
    resident = manager.create()

    assert manager.update_lod(resident.resident_id, 100.0, 0.0, 0.0, 0.0, 0.1) == 0
    assert resident.lod_update_due is True

    assert manager.update_lod(resident.resident_id, 1000.0, 0.0, 0.0, 0.0, 0.1) == 1
    assert manager.update_lod(resident.resident_id, 2000.0, 0.0, 0.0, 0.0, 0.1) == 2