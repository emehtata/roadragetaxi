from theroadragetrip import load_local_sample


def test_sample_exists_and_is_list():
    els = load_local_sample()
    assert els is not None and isinstance(els, list) and len(els) > 0
